"""DataUpdateCoordinator for HP Printer Monitor integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import io
import logging
import xml.etree.ElementTree as ET

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DEVICE_STATUS_MAP,
    DOMAIN,
    EVENT_CODE_MAP,
    PRINTER_STATUS_MAP,
    SNMP_COMMUNITY,
    SNMP_OID_DEVICE_STATUS,
    SNMP_OID_ERROR_STATE,
    SNMP_OID_PRINTER_STATUS,
    SNMP_PORT,
    XML_URL_PATH,
    XML_LOGS_URL_PATH,
)

_LOGGER = logging.getLogger(__name__)


class HPPrintCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch HP printer XML data."""

    def __init__(
        self, hass: HomeAssistant, host: str, scan_interval: int = DEFAULT_SCAN_INTERVAL
    ) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.host = host
        self._scan_interval = scan_interval
        self._session: aiohttp.ClientSession | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session (HTTP, no SSL needed)."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _async_update_data(self):
        """Fetch XMLs + SNMP status in parallel, combine into one dict."""
        usage_data, logs_data, snmp_data = await asyncio.gather(
            self._fetch_and_parse(XML_URL_PATH, self._parse_usage_xml),
            self._fetch_and_parse(XML_LOGS_URL_PATH, self._parse_logs_xml),
            self._query_snmp_status(),
            return_exceptions=True,
        )

        # Unwrap exceptions from gather
        if isinstance(usage_data, Exception):
            _LOGGER.error("ProductUsageDyn.xml fetch failed: %s", usage_data)
            usage_data = None
        if isinstance(logs_data, Exception):
            _LOGGER.error("ProductLogsDyn.xml fetch failed: %s", logs_data)
            logs_data = None
        if isinstance(snmp_data, Exception):
            _LOGGER.error("SNMP status query failed: %s", snmp_data)
            snmp_data = None

        if usage_data is None:
            raise UpdateFailed("Failed to fetch printer usage XML")

        combined = dict(usage_data)
        if logs_data is not None:
            combined.update(logs_data)
        if snmp_data is not None:
            combined.update(snmp_data)

        return combined

    # ── SNMP status query ──────────────────────────────────

    async def _query_snmp_status(self) -> dict | None:
        """Query printer status via SNMP (run in executor)."""
        try:
            result = await self.hass.async_add_executor_job(
                self._snmp_get_status
            )
            return result
        except Exception as err:
            _LOGGER.warning("SNMP status query failed: %s", err)
            return None

    def _snmp_get_status(self) -> dict:
        """Sync SNMP GET using pure-Python client (stdlib only, no pysnmp dep)."""
        from .snmp_client import snmp_get

        oids = {
            "device_status": SNMP_OID_DEVICE_STATUS,
            "printer_status": SNMP_OID_PRINTER_STATUS,
            "error_state": SNMP_OID_ERROR_STATE,
        }

        result: dict[str, str] = {}
        for key, oid in oids.items():
            try:
                raw = snmp_get(self.host, oid, SNMP_COMMUNITY, SNMP_PORT, timeout=3)
                if raw is not None:
                    result[key] = raw
            except Exception as err:
                _LOGGER.debug("SNMP %s (%s) failed: %s", key, oid, err)

        if not result:
            return {}

        # Map numeric status to human-readable text
        data: dict[str, int | str] = {}
        if "device_status" in result:
            raw = result["device_status"]
            data["device_status_raw"] = int(raw) if raw.isdigit() else -1
            data["device_status"] = DEVICE_STATUS_MAP.get(
                data["device_status_raw"], f"未知({raw})"
            )
        if "printer_status" in result:
            raw = result["printer_status"]
            data["printer_status_raw"] = int(raw) if raw.isdigit() else -1
            data["printer_status"] = PRINTER_STATUS_MAP.get(
                data["printer_status_raw"], f"未知({raw})"
            )
        if "error_state" in result:
            raw = result["error_state"]
            data["error_state_raw"] = int(raw) if raw.isdigit() else -1
            data["error_state"] = "正常" if raw == "0" or raw == "" else f"错误({raw})"

        return data

    async def _fetch_and_parse(
        self, path: str, parser, *, accept_404: bool = True
    ) -> dict | None:
        """Fetch an XML endpoint and parse it, returning a dict or None."""
        url = f"http://{self.host}{path}"
        session = self._get_session()
        req_timeout = aiohttp.ClientTimeout(total=15)

        for attempt in range(3):
            try:
                async with session.get(url, timeout=req_timeout) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        if len(content) > 100:
                            _LOGGER.debug(
                                "%s fetched: %d bytes", path, len(content)
                            )
                            return await self.hass.async_add_executor_job(
                                parser, content
                            )
                        _LOGGER.warning("%s too short: %d bytes", path, len(content))
                        return None
                    if accept_404 and resp.status == 404:
                        _LOGGER.debug("%s not available (404), skipping", path)
                        return None
                    _LOGGER.warning("%s returned status %d", path, resp.status)
                    return None
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.warning(
                    "%s attempt %d/3 failed: %s", path, attempt + 1, err
                )
            except Exception as err:
                _LOGGER.error("%s unexpected error attempt %d: %s", path, attempt + 1, err)

            if attempt < 2:
                await asyncio.sleep(2)

        return None

    # ── XML helpers ────────────────────────────────────────

    @staticmethod
    def _strip_namespace(xml_bytes: bytes) -> ET.Element:
        """Strip namespace prefixes from XML tags."""
        it = ET.iterparse(io.BytesIO(xml_bytes))
        for _, el in it:
            if "}" in el.tag:
                el.tag = el.tag.split("}", 1)[1]
        return it.root

    @staticmethod
    def _get_value(root: ET.Element, tag: str, peid: int | None = None) -> int:
        """Extract an integer value from XML by tag and optional PEID."""
        try:
            for el in root.findall(f".//{tag}"):
                if peid is None or el.attrib.get("PEID") == str(peid):
                    text = el.text.strip() if el.text else "0"
                    return int(text)
        except (ValueError, TypeError):
            pass
        return 0

    @staticmethod
    def _get_text(
        root: ET.Element, tag: str, peid: int | None = None
    ) -> str | None:
        """Extract text value from XML by tag and optional PEID."""
        try:
            for el in root.findall(f".//{tag}"):
                if peid is None or el.attrib.get("PEID") == str(peid):
                    return el.text.strip() if el.text else ""
        except (ValueError, TypeError, AttributeError):
            pass
        return None

    # ── Usage XML parsing (ProductUsageDyn.xml) ────────────

    def _parse_usage_xml(self, content: bytes) -> dict:
        """Parse ProductUsageDyn.xml into a flat data dictionary."""
        root = self._strip_namespace(content)
        data: dict[str, int | float | str] = {}

        data.update(self._parse_printer_subunit(root))
        data.update(self._parse_scanner_subunit(root))
        data.update(self._parse_copy_subunit(root))
        data.update(self._parse_fax_subunit(root))
        data.update(self._parse_print_app_subunit(root))
        data.update(self._parse_consumable_subunit(root))

        return data

    def _parse_printer_subunit(self, root: ET.Element) -> dict:
        subunit = root.find(".//PrinterSubunit") or root
        return {
            "engine_total_pages": self._get_value(subunit, "TotalImpressions", 5082),
            "mono_pages": self._get_value(subunit, "MonochromeImpressions"),
            "color_pages": self._get_value(subunit, "ColorImpressions"),
            "simplex_pages": self._get_value(subunit, "SimplexSheets"),
            "duplex_pages": self._get_value(subunit, "TotalImpressions", 5088),
            "print_jam_count": self._get_value(subunit, "JamEvents", 16076),
            "print_mispick_count": self._get_value(subunit, "MispickEvents"),
            "ews_access_count": self._get_value(subunit, "EWSAccessCount", 16081),
            "network_impressions": self._get_value(subunit, "NetworkImpressions", 25000),
            "wireless_impressions": self._get_value(subunit, "WirelessNetworkImpressions", 25002),
        }

    def _parse_scanner_subunit(self, root: ET.Element) -> dict:
        subunit = root.find(".//ScannerEngineSubunit") or root
        return {
            "adf_scan_pages": self._get_value(subunit, "AdfImages", 6011),
            "flatbed_scan_pages": self._get_value(subunit, "FlatbedImages"),
            "scan_jam_count": self._get_value(subunit, "JamEvents"),
            "scan_mispick_count": self._get_value(subunit, "MispickEvents"),
            "scan_total_images": self._get_value(subunit, "ScanImages", 6000),
        }

    def _parse_copy_subunit(self, root: ET.Element) -> dict:
        subunit = root.find(".//CopyApplicationSubunit") or root
        return {
            "copy_total_pages": self._get_value(subunit, "TotalImpressions", 3019),
            "copy_color_pages": self._get_value(subunit, "ColorImpressions"),
            "copy_mono_pages": self._get_value(subunit, "MonochromeImpressions"),
        }

    def _parse_fax_subunit(self, root: ET.Element) -> dict:
        subunit = root.find(".//FaxApplicationSubunit") or root
        return {
            "fax_total_pages": self._get_value(subunit, "TotalImpressions", 4016),
            "fax_color_pages": self._get_value(subunit, "ColorImpressions"),
            "fax_mono_pages": self._get_value(subunit, "MonochromeImpressions"),
        }

    def _parse_print_app_subunit(self, root: ET.Element) -> dict:
        subunit = root.find(".//PrintApplicationSubunit") or root
        return {
            "print_app_total_pages": self._get_value(subunit, "TotalImpressions", 7009),
            "print_app_photo_pages": self._get_value(subunit, "PhotoImpressions", 7002),
        }

    def _parse_consumable_subunit(self, root: ET.Element) -> dict:
        data: dict[str, int | float | str] = {}
        consumable_subunit = root.find(".//ConsumableSubunit")
        if consumable_subunit is None:
            return data

        for consumable in consumable_subunit.findall("Consumable"):
            color_el = consumable.find("MarkerColor")
            if color_el is None:
                continue
            color = color_el.text.strip() if color_el.text else "Unknown"
            cl = color.lower()
            pfx = f"ink_{cl}"

            cc_el = consumable.find("CumulativeConsumableCount")
            if cc_el is not None and cc_el.text:
                val = cc_el.text.strip()
                data[f"{pfx}_cartridge_count"] = int(val) if val.isdigit() else val

            rpl_el = consumable.find("ConsumableRawPercentageLevelRemaining")
            if rpl_el is not None and rpl_el.text:
                val = rpl_el.text.strip()
                if val.lstrip("-").isdigit():
                    data[f"{pfx}_level_remaining"] = int(val)

            state_el = consumable.find("ConsumableState")
            if state_el is not None and state_el.text:
                data[f"{pfx}_state"] = state_el.text.strip()

            for tag, suffix in [
                ("CumulativeMarkingAgentUsed", "ink_used_ml"),
                ("CumulativeHPMarkingAgentUsed", "hp_ink_used_ml"),
            ]:
                parent = consumable.find(tag)
                if parent is not None:
                    vf = parent.find("ValueFloat")
                    if vf is not None and vf.text:
                        try:
                            data[f"{pfx}_{suffix}"] = float(vf.text.strip())
                        except ValueError:
                            pass

            sn_el = consumable.find("SupplySerialNumber")
            if sn_el is not None and sn_el.text:
                data[f"{pfx}_serial"] = sn_el.text.strip()

        return data

    # ── Event log parsing (ProductLogsDyn.xml) ─────────────

    def _parse_logs_xml(self, content: bytes) -> dict:
        """Parse ProductLogsDyn.xml — return all events sorted by time desc."""
        root = self._strip_namespace(content)
        data: dict[str, int | list[dict]] = {
            "event_log_total_count": 0,
            "event_log_data": [],
        }

        event_log = root.find(".//EventLog")
        if event_log is None:
            return data

        events_xml = event_log.findall("Event")
        if not events_xml:
            return data

        data["event_log_total_count"] = len(events_xml)

        # Build event list — XML order is newest first (highest seq)
        event_list = []
        for evt in events_xml:
            seq = self._get_value(evt, "SequenceNumber")
            code = self._get_text(evt, "EventCode") or ""
            ts = self._get_text(evt, "TimeStamp") or ""
            occ = self._get_value(evt, "EventOccurrences")
            pages = self._get_value(evt, "TotalImpressions", 5000)

            # Convert ISO "2026-07-08T09:16:58.0Z" → "2026-07-08 09:16:58"
            time_str = ts.replace("T", " ").split(".")[0] if ts else ""

            event_list.append({
                "time": time_str,
                "seq": seq,
                "code": code,
                "description": EVENT_CODE_MAP.get(code, f"未知事件 ({code})"),
                "occurrences": occ,
                "pages": pages,
            })

        # Already newest-first from XML, but sort by time desc as safety
        event_list.sort(key=lambda e: e["time"], reverse=True)
        data["event_log_data"] = event_list

        return data

    async def async_shutdown(self) -> None:
        """Close the session on shutdown."""
        if self._session and not self._session.closed:
            await self._session.close()
        await super().async_shutdown()
