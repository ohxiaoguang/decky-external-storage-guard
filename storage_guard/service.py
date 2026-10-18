import asyncio
from datetime import datetime, timezone
from pathlib import Path
from .commands import ReadFailure
from .devices import scan
from .journal import read_journal, WINDOWS
from .events import analyze


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

    async def close(self):
        self.closed = True
        if self.active:
            self.active.cancel()
            await asyncio.gather(self.active, return_exceptions=True)

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
            journal = await read_journal(window)
        except (ReadFailure, OSError) as exc:
            journal = {"status": getattr(exc, "status", "read_failed"), "message": str(exc), "records": [], "limited": False}
        events, event_limit = analyze(journal.pop("records"), devices, excluded, boot_id())
        for d in devices:
            related = [e for e in events if e["deviceId"] == d["id"]]
            d["counts"] = {level: sum(e["severity"] == level for e in related) for level in ("Error", "Warning", "Info")}
            d["lastEvent"] = next((e["timestamp"] for e in related if e["severity"] != "Info"), None)
        journal["limited"] |= event_limit
        return {"devices": devices, "deviceStatus": device_status, "journalStatus": journal,
                "events": events, "warnings": warnings, "window": window,
                "refreshedAt": datetime.now(timezone.utc).timestamp() * 1000}
