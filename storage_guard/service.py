import asyncio
from datetime import datetime, timezone
from pathlib import Path
from .commands import ReadFailure
from .devices import scan
from .journal import read_journal, WINDOWS
from .events import analyze
from .remount import Remounter
from .operation_store import OperationStore


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
        self.operation_store = OperationStore()
        self.last_operation = self.operation_store.load()

    async def close(self):
        self.closed = True
        if self.active:
            # Do not interrupt a transaction between successful unmount and its
            # mount attempt merely because the menu/requester has disappeared.
            if not self.managing:
                self.active.cancel()
            await asyncio.gather(self.active, return_exceptions=True)
        self.remounter.grants.clear()

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
        def progress(value, required):
            self.last_operation = {**value, "status": "running", "message": "设备操作进行中，请勿拔出设备或卸载插件"}
            try:
                self.operation_store.save(self.last_operation)
            except OSError as exc:
                if required:
                    raise ReadFailure("state_write_failed", "无法记录操作状态，尚未卸载，已拒绝执行") from exc
                value["warnings"].append("操作记录写入失败；若插件被中断，请以真实挂载状态为准")
        operation = await self.remounter.execute(token, boot_id(), progress)
        operation["finishedAt"] = datetime.now(timezone.utc).timestamp() * 1000
        self.last_operation = operation
        try:
            self.operation_store.save(operation)
        except OSError:
            operation["warnings"].append("最终操作记录未能写入；当前会话仍保留结果，请核对真实状态")
        # Refresh real device state and current-boot logs on *all* outcomes,
        # including command failures/timeouts. Never synthesize a mounted state.
        snapshot = await self._snapshot("boot")
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

    async def _snapshot(self, window):
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
        safety_records, safety_readable = records, journal["status"] == "ok" and not journal["limited"]
        if window != "boot":
            try:
                current_journal = await read_journal("boot")
                safety_records, safety_readable = current_journal["records"], current_journal["status"] == "ok" and not current_journal["limited"]
            except ReadFailure:
                safety_records, safety_readable = [], False
        self.remounter.decorate(devices, safety_records, current_boot, safety_readable)
        for d in devices:
            related = [e for e in events if e["deviceId"] == d["id"]]
            d["counts"] = {level: sum(e["severity"] == level for e in related) for level in ("Error", "Warning", "Info")}
            d["lastEvent"] = next((e["timestamp"] for e in related if e["severity"] != "Info"), None)
        journal["limited"] |= event_limit
        return {"devices": devices, "deviceStatus": device_status, "journalStatus": journal,
                "events": events, "warnings": warnings, "window": window, "lastOperation": self.last_operation,
                "refreshedAt": datetime.now(timezone.utc).timestamp() * 1000}
