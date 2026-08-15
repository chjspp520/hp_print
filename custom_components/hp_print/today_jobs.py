"""今日作业记录传感器：根据累计计数器的变化推断今日打印/扫描/复印/传真作业。

实现原理
--------
打印机自身不提供逐条作业日志，但累计计数器（print_app_total_pages 等）是只增不减的。
本模块在每次 coordinator 刷新时对比累计值：
  - 值增大   → 说明该类别有作业在进行（若之前空闲则开启一条新作业，T1=上次采样时间）
  - 值不变   → 说明空闲（若之前有进行中记录则闭合该作业，T2=本次采样时间）
  - 作业记录 = { time: T1~T2, count: 差值, duration: 间隔秒 }
卡纸事件从 ProductLogsDyn.xml 的事件日志中按当天 + EventCode=15.00.00 提取（带真实时间戳）。

注意
----
- time 是采样区间而非真实作业起止，误差为一次轮询间隔（默认 60 秒），可接受。
- 数据持久化到 .storage/hp_print.today_jobs_{entry_id}.json，HA 重启不丢失。
- 进行中记录超过 JOB_STALE_SECONDS 无进展则判定为异常中断并丢弃。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import homeassistant.util.dt as dt_util

from .const import DOMAIN, EVENT_CODE_MAP, STORAGE_VERSION
from .coordinator import HPPrintCoordinator

_LOGGER = logging.getLogger(__name__)

# 内部自驱动轮询间隔（秒）：不依赖 coordinator 事件，主动读取最新数据
POLL_INTERVAL = 5

# 类别 → 累计计数器 key（与 const.PERIOD_SOURCE_MAP 中的来源一致）
JOB_CATEGORIES = {
    "print": "print_app_total_pages",
    "scan": "scan_total_images",
    "copy": "copy_total_pages",
    "fax": "fax_total_pages",
}

# 卡纸事件码（PrinterSubunit 的 JamEvents 也累计，但这里用事件日志时间戳更精确）
JAM_EVENT_CODE = "15.00.00"

# 存储键
STORAGE_KEY = "hp_print.today_jobs"


class TodayJobsStore:
    """包装 HA Store，持久化今日作业记录。"""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store[dict](hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry_id}")

    async def load(self) -> dict:
        """加载持久化数据，返回空默认结构。"""
        data = await self._store.async_load()
        if data is None:
            return {
                "date": _today_str(),
                "print": [],
                "scan": [],
                "copy": [],
                "fax": [],
                "jam_printer": [],
            }
        data.setdefault("date", _today_str())
        for cat in JOB_CATEGORIES:
            data.setdefault(cat, [])
        data.setdefault("jam_printer", [])
        return data

    async def save(self, data: dict) -> None:
        """持久化数据。"""
        await self._store.async_save(data)


def _today_str() -> str:
    """今日日期字符串（本地时区）。"""
    return dt_util.now().date().isoformat()


def _now_ts() -> str:
    """当前本地时间戳，格式 '2026-08-07 12:10:25'。"""
    return dt_util.now().strftime("%Y-%m-%d %H:%M:%S")


def _is_same_day(ts: str, day: str) -> bool:
    """判断时间戳（'YYYY-MM-DD HH:MM:SS' 或 ISO）是否属于指定日期。"""
    return ts[:10] == day


class TodayJobsSensor(CoordinatorEntity, SensorEntity):
    """今日作业记录传感器。

    state = 今日日期。
    attributes 结构：
      print / scan / copy / fax:
        - id: 递增序号
        - time: "T1 - T2"（采样区间）
        - count: 页数/张数
        - duration: 秒
      jam_printer:
        - id, time, description（来自事件日志）
    """

    _attr_icon = "mdi:file-clock-outline"
    _attr_has_entity_name = True
    _attr_name = "今日作业记录"

    def __init__(
        self,
        coordinator: HPPrintCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """初始化。"""
        super().__init__(coordinator)
        self._entry_id = entry.entry_id
        self._store = TodayJobsStore(coordinator.hass, entry.entry_id)
        self._attr_unique_id = f"{entry.entry_id}_today_jobs"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "HP",
        }

        # 已加载的持久化数据（内存镜像，写盘后同步）
        self._data: dict = {
            "date": _today_str(),
            "print": [],
            "scan": [],
            "copy": [],
            "fax": [],
            "jam_printer": [],
        }
        self._loaded = False

        # 进行中作业跟踪：{cat: {"start_val": int, "start_ts": str, "last_val": int}}
        self._active: dict[str, dict] = {}

        # 脏标记：数据有新增（作业/卡纸）时置 True，落库后清 False，避免每轮都写盘
        self._dirty = False

        # 卡纸去重：记录已处理的事件（seq, time）组合
        self._seen_jam: set[tuple] = set()

        # 自驱动轮询任务句柄
        self._poll_task: asyncio.Task | None = None

        # 已处理的 coordinator 数据快照 id（用于去重：同一快照只处理一次，
        # 避免轮询与 coordinator 更新事件重复处理同一份数据）
        self._last_processed_id: int | None = None

    # ── 生命周期 ──────────────────────────────────────────

    async def async_added_to_hass(self) -> None:
        """加载存储、初始化进行中状态，并启动自驱动轮询任务。

        自驱动轮询不依赖 coordinator 的更新事件，确保实时记录始终工作。
        """
        await super().async_added_to_hass()
        try:
            await self._ensure_loaded()
            # 初始化 seen_jam 为已记录事件的标识，避免重复
            for evt in self._data.get("jam_printer", []):
                seq = evt.get("seq")
                t = evt.get("time")
                if seq is not None and t:
                    self._seen_jam.add((seq, t))
            self._process_coordinator_data()
        except Exception:
            _LOGGER.exception("今日作业: async_added_to_hass 初始化异常")
        self.async_write_ha_state()
        # 启动自驱动轮询任务
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def async_will_remove_from_hass(self) -> None:
        """移除时取消轮询任务。"""
        if hasattr(self, "_poll_task") and self._poll_task:
            self._poll_task.cancel()
        await super().async_will_remove_from_hass()

    async def _poll_loop(self) -> None:
        """自驱动轮询：周期读取 coordinator.data 并处理，不依赖 coordinator 事件。"""
        while True:
            try:
                # 等待一轮，让首次初始化完成且 coordinator 有数据
                await asyncio.sleep(POLL_INTERVAL)
                if self.coordinator.data is not None:
                    self._process_coordinator_data()
                    if self._dirty:
                        self._dirty = False
                        await self._store.save(self._data)
                    self.async_write_ha_state()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("今日作业: 自驱动轮询异常")

    # ── 存储 ──────────────────────────────────────────────

    async def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._data = await self._store.load()
            self._loaded = True

    # ── 数据驱动 ──────────────────────────────────────────

    def _process_coordinator_data(self) -> None:
        """处理 coordinator 最新数据：推断作业 + 提取卡纸事件。

        同一份数据快照只处理一次（用 id 去重），因此无论由轮询还是由
        coordinator 更新事件触发，都不会重复推进状态机。
        """
        data = self.coordinator.data
        if data is None:
            _LOGGER.debug("今日作业: coordinator.data 为 None")
            return

        if id(data) == self._last_processed_id:
            return
        self._last_processed_id = id(data)

        now = _now_ts()
        today = _today_str()

        # 若跨天，清空旧数据并归档当日日期
        if self._data.get("date") != today:
            self._data = {
                "date": today,
                "print": [],
                "scan": [],
                "copy": [],
                "fax": [],
                "jam_printer": [],
            }
            self._active = {cat: {} for cat in JOB_CATEGORIES}
            self._seen_jam = set()

        # 1) 处理四类累计计数器
        for cat, counter_key in JOB_CATEGORIES.items():
            raw = data.get(counter_key)
            if raw is None:
                # 数据缺失：跳过本轮，不推进该类别状态机
                continue
            try:
                val = int(raw)
            except (TypeError, ValueError):
                continue
            self._update_category(cat, val, now)

        # 2) 提取今日卡纸事件（带真实时间戳）
        self._collect_jams(data, today)

    def _update_category(self, cat: str, val: int, now: str) -> None:
        """根据累计值变化推进单个类别的状态机。

        状态机：
          - 空闲（无 active）：
              * val 增大 → 开启作业（start_val=空闲期记录的基线，T1=空闲期最后时间）
              * 首轮无基线时仅初始化基线，不误判为新作业
          - 作业中（有 active）：
              * val 增大 → 更新 last_val（作业持续），T1 保持作业开始时刻
              * val 不变 → 空闲，闭合作业（T2=now）
              * val 减小 → 计数器回落，丢弃
        """
        active = self._active.get(cat)
        # 空闲期基线：上一次空闲时的累计值（作为下个作业的起点）
        base_val = self._data.get(f"_{cat}_base_val")
        base_ts = self._data.get(f"_{cat}_base_ts")

        if not active:
            if base_val is None:
                # 首轮：只初始化基线，不开启作业（基线必须落库，否则重启后丢失）
                self._data[f"_{cat}_base_val"] = val
                self._data[f"_{cat}_base_ts"] = now
                self._dirty = True
                _LOGGER.debug(
                    "今日作业 %s: 初始化基线=%s (time=%s)", cat, val, now
                )
                return
            if val > base_val:
                # 有新作业开始：T1 = 上次基线时间
                _LOGGER.info(
                    "今日作业 %s: 检测到计数增加 %s→%s，开启作业", cat, base_val, val
                )
                self._active[cat] = {
                    "start_val": base_val,
                    "start_ts": base_ts or now,
                    "last_val": val,
                }
            else:
                # 空闲，刷新基线时间（保持值，供下个作业作为 T1）
                self._data[f"_{cat}_base_ts"] = now
            return

        last_val = active["last_val"]
        if val > last_val:
            # 作业持续中
            active["last_val"] = val
        elif val == last_val:
            # 作业结束
            self._close_job(cat, active["start_val"], active["start_ts"], now)
            self._active[cat] = {}
            # 更新空闲基线为当前值，供下一作业使用
            self._data[f"_{cat}_base_val"] = val
            self._data[f"_{cat}_base_ts"] = now
        else:
            # 计数器回落，丢弃进行中记录
            _LOGGER.debug(
                "今日作业 %s: 计数器回落 %s→%s，丢弃进行中记录", cat, last_val, val
            )
            self._active[cat] = {}
            self._data[f"_{cat}_base_val"] = val
            self._data[f"_{cat}_base_ts"] = now

    def _close_job(self, cat: str, start_val: int, start_ts: str, now: str) -> None:
        """闭合一条作业记录。start_val=作业起点累计值, start_ts=作业开始时间。"""
        active = self._active.get(cat)
        if not active:
            return
        end_val = active["last_val"]
        count = end_val - start_val
        if count < 0:
            count = 0

        # 计算作业时长（秒）
        try:
            start_dt = datetime.strptime(start_ts, "%Y-%m-%d %H:%M:%S")
            end_dt = datetime.strptime(now, "%Y-%m-%d %H:%M:%S")
            duration = int((end_dt - start_dt).total_seconds())
        except ValueError:
            duration = 0

        # 超时兜底：仅当"没有实际打印量"（count==0）却出现疑似未闭合作业时丢弃。
        # 注意：不能因为 duration 长就丢弃——打印机待机/唤醒可能导致 start_ts 陈旧，
        # 此时 count>0 说明确实发生过打印，必须保留。中断场景由 count==0 兜底。
        if count <= 0:
            _LOGGER.debug(
                "今日作业 %s: 无实际打印量（count=%d），丢弃", cat, count
            )
            return

        job = {
            "id": len(self._data.get(cat, [])) + 1,
            "time": f"{start_ts} - {now}",
            "count": count,
            "duration": duration,
        }
        self._data.setdefault(cat, []).append(job)
        self._dirty = True
        _LOGGER.info("今日作业 %s: 记录 %s 页, 耗时 %ds", cat, count, duration)

    def _collect_jams(self, data: dict, today: str) -> None:
        """从事件日志提取今日卡纸事件并去重追加。"""
        events = data.get("event_log_data", [])
        if not events:
            return
        for evt in events:
            code = evt.get("code", "")
            if code != JAM_EVENT_CODE:
                continue
            ts = evt.get("time", "")
            seq = evt.get("seq", 0)
            if not ts or not _is_same_day(ts, today):
                continue
            key = (seq, ts)
            if key in self._seen_jam:
                continue
            self._seen_jam.add(key)
            self._data.setdefault("jam_printer", []).append({
                "id": len(self._data.get("jam_printer", [])) + 1,
                "time": ts,
                "seq": seq,
                "description": EVENT_CODE_MAP.get(code, "卡纸"),
            })
            self._dirty = True
            _LOGGER.info("今日作业: 记录卡纸事件 %s %s", ts, code)

    def _handle_coordinator_update(self) -> None:
        """coordinator 数据更新时，立即处理最新数据并刷新 state。

        处理本身是幂等的（同一快照只处理一次），与自驱动轮询共享
        _process_coordinator_data，避免竞态与重复记录。
        """
        try:
            self._process_coordinator_data()
            if self._dirty:
                self._dirty = False
                self.hass.async_create_task(self._store.save(self._data))
            super()._handle_coordinator_update()
        except Exception:
            _LOGGER.exception("今日作业: _handle_coordinator_update 异常")

    # ── 传感器属性 ────────────────────────────────────────

    def _total_jobs(self) -> int:
        """今日作业合计 = print/scan/copy/fax 各条记录数 + 卡纸事件条数。"""
        total = 0
        for cat in JOB_CATEGORIES:
            total += len(self._data.get(cat, []))
        total += len(self._data.get("jam_printer", []))
        return total

    @property
    def native_value(self) -> StateType:
        """state = 今日作业合计（print/scan/copy/fax/jam_printer 的记录数之和）。"""
        return self._total_jobs()

    @property
    def extra_state_attributes(self) -> dict:
        """暴露 print/scan/copy/fax/jam_printer 作业列表及合计。"""
        return {
            "print": self._data.get("print", []),
            "scan": self._data.get("scan", []),
            "copy": self._data.get("copy", []),
            "fax": self._data.get("fax", []),
            "jam_printer": self._data.get("jam_printer", []),
            "total": self._total_jobs(),
            "date": self._data.get("date", _today_str()),
        }

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.coordinator.data is not None
