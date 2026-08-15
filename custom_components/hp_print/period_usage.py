"""Period usage sensor: daylist / monthlist / yearlist + total.

Stores lists in .storage/hp_print.period_usage_{entry_id}.json
- daylist/monthlist/yearlist: stored period deltas (e.g. today printed 5 pages)
- total: live values from printer XML (coordinator data), not from list sums
- On first run with empty lists, backfills from HA recorder history.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta

from homeassistant.components.recorder.history import get_significant_states
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import homeassistant.util.dt as dt_util

from .const import (
    DOMAIN,
    INK_COLOR_KEYS,
    PERIOD_KEYS,
    PERIOD_SOURCE_MAP,
    PERIOD_UNIT_MAP,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .coordinator import HPPrintCoordinator

_LOGGER = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Storage helper — async load / save
# ──────────────────────────────────────────────
class PeriodUsageStore:
    """Wrap HA Store to persist baselines and lists."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store[dict](hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry_id}")

    async def load(self) -> dict:
        """Load persisted data or return empty defaults."""
        data = await self._store.async_load()
        if data is None:
            return {"baselines": {}, "daylist": [], "monthlist": [], "yearlist": []}
        data.setdefault("baselines", {})
        data.setdefault("daylist", [])
        data.setdefault("monthlist", [])
        data.setdefault("yearlist", [])
        return data

    async def save(self, data: dict) -> None:
        """Persist data."""
        await self._store.async_save(data)


# ──────────────────────────────────────────────
# Date helpers
# ──────────────────────────────────────────────
def _today_str() -> str:
    return date.today().isoformat()


def _month_str() -> str:
    t = date.today()
    return f"{t.year}-{t.month:02d}"


def _year_str() -> str:
    return str(date.today().year)


# ──────────────────────────────────────────────
# Value extraction
# ──────────────────────────────────────────────
def _abs_from_coord(data: dict, cat: str) -> int:
    """Get absolute cumulative value from coordinator data."""
    key = PERIOD_SOURCE_MAP.get(cat)
    if key is None:
        return 0
    val = data.get(key, 0)
    return int(val) if val is not None else 0


def _get_total(coord_data: dict) -> dict[str, str | int]:
    """Extract current total values directly from coordinator data."""
    result: dict[str, str | int] = {}
    for cat in PERIOD_KEYS:
        result[cat] = _format_entry_value(cat, _abs_from_coord(coord_data, cat))
    return result


def _get_lik(coord_data: dict) -> list[dict[str, str | int]]:
    """Extract ink/consumable info from coordinator data for the 'lik' attribute."""
    result: list[dict[str, str | int]] = []
    for cl in INK_COLOR_KEYS:
        pfx = f"ink_{cl}"
        entry: dict[str, str | int] = {"color": cl}
        remaining = coord_data.get(f"{pfx}_level_remaining")
        entry["remaining"] = f"{remaining}%" if remaining not in (None, "") else ""
        replace_count = coord_data.get(f"{pfx}_cartridge_count")
        entry["replace_count"] = f"{replace_count}次" if replace_count not in (None, "") else ""
        total_usage = coord_data.get(f"{pfx}_ink_used_ml")
        entry["total_usage"] = f"{total_usage}ml" if total_usage not in (None, "") else ""
        entry["status"] = coord_data.get(f"{pfx}_state", "")
        result.append(entry)
    return result


def _safe_delta(current: int, baseline: int) -> int:
    """Return delta; if counter reset (current < baseline), return current."""
    if current < baseline:
        return current
    return current - baseline


def _format_entry_value(cat: str, raw_value: int) -> str | int:
    """Format a period entry value, adding unit suffix for ink keys."""
    unit = PERIOD_UNIT_MAP.get(cat)
    if unit:
        return f"{raw_value}{unit}"
    return raw_value


def _make_delta_entry(
    period_key: str,
    period_val: str,
    coord_data: dict,
    baseline: dict,
    *,
    include_ink: bool = False,
) -> dict:
    """Build a delta entry dict using baseline subtraction.

    For ink keys (ink_black etc.), use snapshot value instead of delta.
    Set include_ink=True to include ink keys (daylist only).
    """
    entry: dict[str, str | int] = {period_key: period_val}
    for cat in PERIOD_KEYS:
        if cat.startswith("ink_"):
            if include_ink:
                entry[cat] = _format_entry_value(cat, _abs_from_coord(coord_data, cat))
            # else: skip ink keys for month/year
        else:
            entry[cat] = _format_entry_value(cat, _safe_delta(
                _abs_from_coord(coord_data, cat),
                baseline.get(cat, 0),
            ))
    return entry


# ──────────────────────────────────────────────
# History backfill
# ──────────────────────────────────────────────
def _state_value(state: State | None) -> int:
    """Extract int value from a HA State object."""
    if state is None or state.state in (None, "unknown", "unavailable"):
        return 0
    try:
        return int(float(state.state))
    except (ValueError, TypeError):
        return 0


def _find_entity_ids(
    hass: HomeAssistant,
    entry_id: str,
) -> dict[str, str]:
    """Map PERIOD_KEYS → actual entity_id by looking up unique_id in entity registry.

    Unique IDs are like "{entry_id}_print_app_total_pages".
    Entity IDs are like "sensor.hp_printer_cai_se_da_yin_ye_shu".
    """
    entity_registry = None
    try:
        from homeassistant.helpers import entity_registry as er
        entity_registry = er.async_get(hass)
    except Exception:
        pass

    result: dict[str, str] = {}
    for cat in PERIOD_KEYS:
        key = PERIOD_SOURCE_MAP.get(cat)
        if not key:
            continue
        unique_id = f"{entry_id}_{key}"

        # Try entity registry first
        if entity_registry:
            entry = entity_registry.async_get_entity_id("sensor", DOMAIN, unique_id)
            if entry:
                result[cat] = entry
                continue

        # Fallback: search hass.states by unique_id in attributes
        for state in hass.states.async_all():
            if state.domain == "sensor" and state.attributes.get("unique_id") == unique_id:
                result[cat] = state.entity_id
                break

    return result


async def _backfill_from_history(
    hass: HomeAssistant,
    entry_id: str,
    daylist_days: int,
) -> tuple[list[dict], list[dict], list[dict], dict]:
    """Query HA recorder history for cumulative sensor entities and backfill
    daylist, monthlist, yearlist with delta entries.

    Returns (daylist, monthlist, yearlist, baselines).
    """
    # Resolve PERIOD_KEYS → actual entity_id via entity registry
    entity_map = _find_entity_ids(hass, entry_id)

    if not entity_map:
        _LOGGER.warning(
            "PeriodUsageSensor: could not resolve any source entities for entry_id=%s, "
            "skipping backfill", entry_id,
        )
        return [], [], [], {}

    entity_ids = list(entity_map.values())
    _LOGGER.info(
        "PeriodUsageSensor: resolved entities for backfill: %s",
        {cat: eid for cat, eid in entity_map.items()},
    )

    # Query all available history (no start_time → from beginning)
    end_time = dt_util.utcnow()
    # Go back 3 years to cover reasonable range
    start_time = end_time - timedelta(days=1095)

    _LOGGER.info(
        "PeriodUsageSensor: backfilling from history for %d entities (%s)",
        len(entity_ids), entity_ids,
    )

    try:
        states_by_entity: dict[str, list[State]] = await hass.async_add_executor_job(
            lambda: get_significant_states(
                hass,
                start_time,
                end_time,
                entity_ids,
                include_start_time_state=True,
                significant_changes_only=False,
                minimal_response=False,
                no_attributes=False,
                compressed_state_format=False,
            )
        )
    except Exception:
        _LOGGER.exception("PeriodUsageSensor: history query failed, skipping backfill")
        return [], [], [], {}

    if not states_by_entity:
        _LOGGER.info("PeriodUsageSensor: no history data found, skipping backfill")
        return [], [], [], {}

    # For each entity, group states by day → take the *last* state of each day
    # This gives us daily cumulative snapshots
    daily_snapshots: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )  # {day: {cat: value}}

    for cat, eid in entity_map.items():
        states = states_by_entity.get(eid, [])
        if not states:
            continue
        for s in states:
            if s.last_updated is None:
                continue
            day_key = s.last_updated.date().isoformat()
            val = _state_value(s)
            # Keep the last value of each day (states are chronologically ordered)
            daily_snapshots[day_key][cat] = val

    if not daily_snapshots:
        _LOGGER.info("PeriodUsageSensor: no daily snapshots from history")
        return [], [], [], {}

    # Sort days ascending
    sorted_days = sorted(daily_snapshots.keys())
    _LOGGER.info(
        "PeriodUsageSensor: found %d days of history, from %s to %s",
        len(sorted_days), sorted_days[0], sorted_days[-1],
    )

    today = _today_str()

    # Compute daily deltas: each day's delta = this day's cumulative - previous day's cumulative
    daylist: list[dict] = []
    month_aggregates: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    year_aggregates: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    # Skip today from backfill — today is computed live by compute_lists
    prev_values: dict[str, int] = {cat: 0 for cat in PERIOD_KEYS}
    first_real_day = True

    for day_key in sorted_days:
        # Skip today (let compute_lists handle it live)
        if day_key == today:
            continue

        snap = daily_snapshots[day_key]
        entry: dict[str, str | int] = {"day": day_key}
        all_zero = True
        for cat in PERIOD_KEYS:
            cur = snap.get(cat, prev_values.get(cat, 0))
            if cat.startswith("ink_"):
                # Ink is a snapshot — use value directly with unit
                entry[cat] = _format_entry_value(cat, cur)
            else:
                delta = _safe_delta(cur, prev_values.get(cat, 0))
                entry[cat] = _format_entry_value(cat, delta)
                prev_values[cat] = cur
                if delta != 0:
                    all_zero = False

        # Skip the very first day if all deltas are zero
        # (that's the include_start_time_state artifact)
        if first_real_day and all_zero:
            first_real_day = False
            continue
        first_real_day = False

        daylist.append(entry)

        # Aggregate into month/year
        month_key = day_key[:7]  # "2026-08"
        year_key = day_key[:4]   # "2026"
        for cat in PERIOD_KEYS:
            if cat.startswith("ink_"):
                # Ink level: take the last day's value for the month/year
                # entry[cat] is already formatted string like "75%", strip unit for aggregation
                month_aggregates[month_key][cat] = _abs_from_coord(
                    {PERIOD_SOURCE_MAP.get(cat, ""): cur}, cat
                )
                year_aggregates[year_key][cat] = month_aggregates[month_key][cat]
            else:
                month_aggregates[month_key][cat] += entry[cat]
                year_aggregates[year_key][cat] += entry[cat]

    # Reverse so newest first
    daylist.reverse()

    # Trim daylist
    if len(daylist) > daylist_days:
        daylist = daylist[:daylist_days]

    # Build monthlist (newest first) — skip ink keys
    monthlist: list[dict] = []
    for mk in sorted(month_aggregates.keys(), reverse=True):
        entry: dict[str, str | int] = {"month": mk}
        for cat in PERIOD_KEYS:
            if cat.startswith("ink_"):
                continue
            entry[cat] = month_aggregates[mk][cat]
        monthlist.append(entry)

    # Build yearlist (newest first) — skip ink keys
    yearlist: list[dict] = []
    for yk in sorted(year_aggregates.keys(), reverse=True):
        entry: dict[str, str | int] = {"year": yk}
        for cat in PERIOD_KEYS:
            if cat.startswith("ink_"):
                continue
            entry[cat] = year_aggregates[yk][cat]
        yearlist.append(entry)

    # Build baselines from the last known cumulative values
    # Use the last non-today day's cumulative as baseline for today
    baselines: dict = {}
    yesterday_cumulative: dict[str, int] = {cat: 0 for cat in PERIOD_KEYS}
    if sorted_days:
        # Find the last non-today day
        for dk in reversed(sorted_days):
            if dk == today:
                continue
            for cat in PERIOD_KEYS:
                yesterday_cumulative[cat] = daily_snapshots[dk].get(cat, 0)
            break

    daily_base = {"date": today}
    for k in PERIOD_KEYS:
        daily_base[k] = yesterday_cumulative.get(k, 0)
    baselines["daily"] = daily_base

    # monthly baseline = current month start
    # We need the last value before this month started
    # For simplicity, use the last snapshot of the previous month
    this_month = _month_str()
    prev_month_snap: dict[str, int] = {}
    for dk in sorted_days:
        if dk[:7] < this_month:
            for cat in PERIOD_KEYS:
                prev_month_snap[cat] = daily_snapshots[dk].get(cat, 0)
    monthly_base = {"month": this_month}
    for cat in PERIOD_KEYS:
        monthly_base[cat] = prev_month_snap.get(cat, 0)
    baselines["monthly"] = monthly_base

    # yearly baseline
    this_year = _year_str()
    prev_year_snap: dict[str, int] = {}
    for dk in sorted_days:
        if dk[:4] < this_year:
            for cat in PERIOD_KEYS:
                prev_year_snap[cat] = daily_snapshots[dk].get(cat, 0)
    yearly_base = {"year": this_year}
    for cat in PERIOD_KEYS:
        yearly_base[cat] = prev_year_snap.get(cat, 0)
    baselines["yearly"] = yearly_base

    _LOGGER.info(
        "PeriodUsageSensor: backfill complete — daylist=%d, monthlist=%d, yearlist=%d",
        len(daylist), len(monthlist), len(yearlist),
    )

    return daylist, monthlist, yearlist, baselines


# ──────────────────────────────────────────────
# Computation
# ──────────────────────────────────────────────
def compute_lists(
    coord_data: dict,
    stored: dict,
    daylist_days: int,
) -> tuple[dict, dict]:
    """Compute updated daylist, monthlist, yearlist using baseline deltas.

    Returns (new_stored_data, attributes_dict).
    """
    baselines: dict = stored.get("baselines", {})
    daylist: list[dict] = list(stored.get("daylist", []))
    monthlist: list[dict] = list(stored.get("monthlist", []))
    yearlist: list[dict] = list(stored.get("yearlist", []))

    today = _today_str()
    this_month = _month_str()
    this_year = _year_str()

    # ── daily ──
    dkey = today
    daily_base = baselines.get("daily")
    if daily_base is None or daily_base.get("date") != dkey:
        # Archive yesterday if we had a baseline
        if daily_base is not None and daily_base.get("date"):
            yesterday = _make_delta_entry(
                "day", daily_base["date"], coord_data, daily_base, include_ink=True,
            )
            daylist.insert(0, yesterday)
        # Reset baseline for today
        daily_base = {"date": dkey}
        for k in PERIOD_KEYS:
            daily_base[k] = _abs_from_coord(coord_data, k)
        baselines["daily"] = daily_base

    # Today's delta entry (latest)
    today_entry = _make_delta_entry(
        "day", dkey, coord_data, daily_base, include_ink=True,
    )
    if daylist and daylist[0].get("day") == dkey:
        daylist[0] = today_entry
    else:
        daylist.insert(0, today_entry)

    # ── monthly ──
    mkey = this_month
    monthly_base = baselines.get("monthly")
    if monthly_base is None or monthly_base.get("month") != mkey:
        if monthly_base is not None and monthly_base.get("month"):
            last_month = _make_delta_entry(
                "month", monthly_base["month"], coord_data, monthly_base,
            )
            monthlist.insert(0, last_month)
        monthly_base = {"month": mkey}
        for k in PERIOD_KEYS:
            monthly_base[k] = _abs_from_coord(coord_data, k)
        baselines["monthly"] = monthly_base

    this_month_entry = _make_delta_entry("month", mkey, coord_data, monthly_base)
    if monthlist and monthlist[0].get("month") == mkey:
        monthlist[0] = this_month_entry
    else:
        monthlist.insert(0, this_month_entry)

    # ── yearly ──
    ykey = this_year
    yearly_base = baselines.get("yearly")
    if yearly_base is None or yearly_base.get("year") != ykey:
        if yearly_base is not None and yearly_base.get("year"):
            last_year = _make_delta_entry(
                "year", yearly_base["year"], coord_data, yearly_base,
            )
            yearlist.insert(0, last_year)
        yearly_base = {"year": ykey}
        for k in PERIOD_KEYS:
            yearly_base[k] = _abs_from_coord(coord_data, k)
        baselines["yearly"] = yearly_base

    this_year_entry = _make_delta_entry("year", ykey, coord_data, yearly_base)
    if yearlist and yearlist[0].get("year") == ykey:
        yearlist[0] = this_year_entry
    else:
        yearlist.insert(0, this_year_entry)

    # ── trim ──
    if len(daylist) > daylist_days:
        daylist = daylist[:daylist_days]

    # ── total: always live from coordinator ──
    total = _get_total(coord_data)

    # ── lik: live ink info from coordinator ──
    lik = _get_lik(coord_data)

    new_stored = {
        "baselines": baselines,
        "daylist": daylist,
        "monthlist": monthlist,
        "yearlist": yearlist,
    }

    attrs = {
        "daylist": daylist,
        "monthlist": monthlist,
        "yearlist": yearlist,
        "total": total,
        "lik": lik,
    }

    return new_stored, attrs


# ──────────────────────────────────────────────
# Sensor entity
# ──────────────────────────────────────────────
class PeriodUsageSensor(CoordinatorEntity, SensorEntity):
    """Sensor exposing daylist / monthlist / yearlist + total attributes.

    State = today's date string.
    """

    _attr_icon = "mdi:chart-bar-stacked"
    _attr_has_entity_name = True
    _attr_name = "用量统计"

    def __init__(
        self,
        coordinator: HPPrintCoordinator,
        entry: ConfigEntry,
        daylist_days: int,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._entry = entry
        self._entry_id = entry.entry_id
        self._store = PeriodUsageStore(coordinator.hass, entry.entry_id)
        self._daylist_days = daylist_days
        self._attr_unique_id = f"{entry.entry_id}_period_usage"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "HP",
        }
        # Cached attributes
        self._daylist: list[dict] = []
        self._monthlist: list[dict] = []
        self._yearlist: list[dict] = []
        self._total: dict[str, int] = {}
        self._lik: list[dict] = []
        self._stored: dict = {
            "baselines": {},
            "daylist": [],
            "monthlist": [],
            "yearlist": [],
        }
        self._loaded = False

    async def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._stored = await self._store.load()
            self._loaded = True

    async def async_added_to_hass(self) -> None:
        """Load stored data, backfill from history if needed, compute initial values."""
        await super().async_added_to_hass()
        await self._ensure_loaded()

        # If all lists are empty, try to backfill from HA history
        if (
            not self._stored.get("daylist")
            and not self._stored.get("monthlist")
            and not self._stored.get("yearlist")
        ):
            _LOGGER.info("PeriodUsageSensor: empty storage, backfilling from history")
            try:
                daylist, monthlist, yearlist, baselines = await _backfill_from_history(
                    self.hass, self._entry_id, self._daylist_days
                )
                if daylist or monthlist or yearlist:
                    self._stored["daylist"] = daylist
                    self._stored["monthlist"] = monthlist
                    self._stored["yearlist"] = yearlist
                    self._stored["baselines"] = baselines
                    # Persist immediately so we don't re-query on next restart
                    await self._store.save(self._stored)
            except Exception:
                _LOGGER.exception("PeriodUsageSensor: backfill failed")

        self._compute_and_persist()
        self.async_write_ha_state()

    @property
    def native_value(self) -> StateType:
        """State = sum of print, scan, copy, fax, jam_printer totals."""
        return sum(
            _abs_from_coord(self.coordinator.data, cat)
            if self.coordinator.data is not None
            else 0
            for cat in ("print", "scan", "copy", "fax", "jam_printer")
        )

    @property
    def extra_state_attributes(self) -> dict:
        """Expose daylist, monthlist, yearlist, total, lik as attributes."""
        return {
            "daylist": self._daylist,
            "monthlist": self._monthlist,
            "yearlist": self._yearlist,
            "total": self._total,
            "lik": self._lik,
        }

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.coordinator.data is not None

    def set_daylist_days(self, days: int) -> None:
        """Update retention days (called from reconfigure listener)."""
        self._daylist_days = days

    def reload_from_stored(self, stored: dict) -> None:
        """Reload cached attributes from a stored dict (used by backfill button).

        After calling this, caller should also call schedule_update_ha_state()
        to push the updated attributes to HA state machine.
        """
        self._stored = stored
        self._daylist = stored.get("daylist", [])
        self._monthlist = stored.get("monthlist", [])
        self._yearlist = stored.get("yearlist", [])

    def _compute_and_persist(self) -> None:
        """Compute lists + total from current coordinator data, persist if changed."""
        try:
            data = self.coordinator.data
            if data is None:
                return

            new_stored, attrs = compute_lists(
                data, self._stored, self._daylist_days
            )

            self._daylist = attrs["daylist"]
            self._monthlist = attrs["monthlist"]
            self._yearlist = attrs["yearlist"]
            self._total = attrs["total"]
            self._lik = attrs["lik"]

            # Persist if changed
            if new_stored != self._stored:
                self._stored = new_stored
                self.hass.async_create_task(self._store.save(new_stored))
        except Exception:
            _LOGGER.exception("PeriodUsageSensor: _compute_and_persist failed")

    def _handle_coordinator_update(self) -> None:
        """Called by coordinator when data updates."""
        self._compute_and_persist()
        super()._handle_coordinator_update()
