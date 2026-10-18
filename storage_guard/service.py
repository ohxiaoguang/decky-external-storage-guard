import asyncio
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from .commands import ReadFailure
from .devices import scan
from .journal import read_journal, WINDOWS
from .events import analyze
from .remount import Remounter
from .suspend import pair_cycles, annotate, history_payload
from .hardware import system_info, enrich_readers, private_identifiers
from .report import build_report, REPORT_WINDOWS
from .export import export_text


def boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip().replace("-", "")
    except OSError:
        return ""


class Service:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.closed = False
        self.active = None
        self.managing = False
        self.remounter = Remounter()
        self.last_operation = None
        self.reports = {}

    async def generate_report(self, window="boot"):
        if window not in REPORT_WINDOWS:
            raise ReadFailure("invalid_request", "报告时间范围不受支持")
        async with self.lock:
            if self.closed:
                raise ReadFailure("unavailable", "插件已卸载")
            self.active = asyncio.create_task(self._make_report(window))
            try:
                return await self.active
            finally:
                self.active = None

    async def _make_report(self, window):
        capture = {}
        snapshot = await self._snapshot(window, capture=capture, management=False)
        await enrich_readers(snapshot["devices"])
        capture["operation"] = self.last_operation
        report = build_report(snapshot, capture, system_info(), private_values=private_identifiers(snapshot["devices"]))
        now = time.monotonic()
        self.reports = {key: value for key, value in self.reports.items() if value["expires"] > now}
        while len(self.reports) >= 2:
            self.reports.pop(next(iter(self.reports)))
        report_id = secrets.token_urlsafe(24)
        self.reports[report_id] = {"text": report["text"], "expires": now + 600}
        return {"status": "ok", "reportId": report_id, **report}

    async def export_report(self, report_id):
        if self.closed:
            raise ReadFailure("unavailable", "插件已卸载")
        report = self.reports.get(report_id) if isinstance(report_id, str) else None
        if not report or report["expires"] <= time.monotonic():
            raise ReadFailure("report_expired", "报告已过期或无效，请重新生成后导出")
        # Export only a cached, sanitized report; no caller-supplied text/path.
        return {"status": "ok", **export_text(report["text"])}

    async def close(self):
        self.closed = True
        if self.active:
            # Do not interrupt a transaction between successful unmount and its
            # mount attempt merely because the menu/requester has disappeared.
            if not self.managing:
                self.active.cancel()
            await asyncio.gather(asyncio.shield(self.active), return_exceptions=True)
        self.remounter.grants.clear()
        self.reports.clear()

    async def remount(self, token: str) -> dict:
        if self.closed:
            raise RuntimeError("插件已卸载")
        if self.lock.locked():
            return {"operation": {"status": "busy", "phase": "validation", "message": "有读取或设备操作正在进行，请稍后刷新重试",
                                  "detail": "", "partition": None, "unmounted": False, "mounted": None, "warnings": []}, "snapshot": None}
        # Acquire before scheduling: simultaneous RPCs must be rejected, not queued.
        await self.lock.acquire()
        self.managing = True
        task = asyncio.create_task(self._remount(token))
        self.active = task

        def finished(_):
            self.managing = False
            self.active = None
            self.lock.release()
        task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def _remount(self, token):
        def progress(value):
            self.last_operation = {**value, "status": "running", "message": "操作中，请勿拔出设备"}
        try:
            operation = await self.remounter.execute(token, boot_id(), progress)
        except asyncio.CancelledError:
            self.last_operation = {**(self.last_operation or {}), "status": "interrupted", "mounted": None,
                                   "unmounted": None if (self.last_operation or {}).get("phase") in ("unmount", "verify_unmount") else (self.last_operation or {}).get("unmounted"),
                                   "message": "操作被中断，结果不确定，请核对真实挂载状态", "warnings": [],
                                   "detail": "不会自动重试；后端强制终止或断电无法保证完成"}
            raise
        except Exception as exc:
            operation = {**(self.last_operation or {}), "status": "unknown", "mounted": None,
                         "message": "操作结果不确定，请核对真实挂载状态", "warnings": [], "detail": type(exc).__name__}
        operation["finishedAt"] = datetime.now(timezone.utc).timestamp() * 1000
        self.last_operation = operation
        try:
            snapshot = await self._snapshot("boot")
        except Exception:
            operation["warnings"].append("最终状态刷新失败，请稍后刷新核对")
            snapshot = None
        return {"operation": operation, "snapshot": snapshot}

    async def snapshot(self, window: str = "boot") -> dict:
        if window not in WINDOWS:
            raise ValueError("不支持的日志时间范围")
        if self.closed:
            raise RuntimeError("插件已卸载")
        # Serialize menu requests; no resident tasks or polling.
        async with self.lock:
            if self.closed:
                raise RuntimeError("插件已卸载")
            self.active = asyncio.create_task(self._snapshot(window))
            try:
                return await self.active
            finally:
                self.active = None

    async def _snapshot(self, window, capture=None, management=True):
        devices, excluded, warnings = [], [], []
        device_status = {"status": "ok", "message": "设备扫描完成"}
        try:
            devices, excluded, warnings = await scan()
        except (ReadFailure, ValueError, OSError, KeyError, TypeError) as exc:
            device_status = {"status": getattr(exc, "status", "read_failed"), "message": f"设备扫描失败：{exc}"}
        try:
            journal = dict(await read_journal(window))
        except (ReadFailure, OSError) as exc:
            journal = {"status": getattr(exc, "status", "read_failed"), "message": str(exc), "records": [], "limited": False}
        records = journal.pop("records")
        current_boot = boot_id()
        events, event_limit = analyze(records, devices, excluded, current_boot)
        cycles = pair_cycles(records)
        annotate(events, cycles)
        if any(not r.get("_BOOT_ID") or r.get("__REALTIME_TIMESTAMP") is None or r.get("__MONOTONIC_TIMESTAMP") is None for r in records):
            warnings.append("部分日志缺少 Boot ID 或结构化时钟字段，相关时间关系只能估计或标记未知")
        safety_records, safety_readable = records, journal["status"] == "ok" and not journal["limited"]
        if management and window != "boot":
            try:
                current_journal = await read_journal("boot")
                safety_records, safety_readable = current_journal["records"], current_journal["status"] == "ok" and not current_journal["limited"]
            except ReadFailure:
                safety_records, safety_readable = [], False
        if management:
            self.remounter.decorate(devices, safety_records, current_boot, safety_readable)
        if capture is not None:
            contexts, _ = analyze(records, devices, excluded, current_boot, include_context=True, max_events=12000)
            capture.update(records=records, contextRecords=[e["record"] for e in contexts], cycles=cycles)
        for d in devices:
            related = [e for e in events if e["deviceId"] == d["id"]]
            d["counts"] = {level: sum(e["severity"] == level for e in related) for level in ("Error", "Warning", "Info")}
            d["lastEvent"] = next((e["timestamp"] for e in related if e["severity"] != "Info"), None)
        journal["limited"] |= event_limit
        sleep_history = history_payload(cycles, events, journal)
        return {"devices": devices, "deviceStatus": device_status, "journalStatus": journal,
                "events": events, "warnings": warnings, "window": window, "lastOperation": self.last_operation,
                "sleepHistory": sleep_history,
                "refreshedAt": datetime.now(timezone.utc).timestamp() * 1000}
