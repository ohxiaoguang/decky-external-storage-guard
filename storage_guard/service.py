import asyncio
from datetime import datetime, timezone
from .commands import ReadFailure
from .devices import scan
from .journal import read_journal
from .remount import PartitionManager


class Service:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.log_lock = asyncio.Lock()
        self.closed = False
        self.active = None
        self.log_task = None
        self.managing = False
        self.manager = PartitionManager()
        self.last_operation = None

    async def close(self):
        self.closed = True
        if self.log_task:
            self.log_task.cancel()
            await asyncio.gather(self.log_task, return_exceptions=True)
        if self.active:
            if not self.managing:
                self.active.cancel()
            await asyncio.gather(asyncio.shield(self.active), return_exceptions=True)
        self.manager.grants.clear()
        self.manager.options.clear()

    async def snapshot(self):
        async with self.lock:
            if self.closed:
                raise RuntimeError("插件已卸载")
            self.active = asyncio.create_task(self._snapshot())
            try:
                return await self.active
            finally:
                self.active = None

    async def _snapshot(self):
        try:
            devices, _, warnings = await scan()
            self.manager.decorate(devices)
            status = {"status": "ok", "message": ""}
        except (ReadFailure, ValueError, OSError, KeyError, TypeError) as exc:
            devices, warnings = [], []
            status = {"status": getattr(exc, "status", "read_failed"), "message": f"设备读取失败：{exc}"}
        return {"devices": devices, "deviceStatus": status, "lastOperation": self.last_operation}

    async def logs(self):
        async with self.log_lock:
            if self.closed:
                raise ReadFailure("unavailable", "插件已卸载")
            self.log_task = asyncio.create_task(read_journal())
            try:
                return await self.log_task
            finally:
                self.log_task = None

    async def operate(self, action, token):
        if self.closed:
            raise RuntimeError("插件已卸载")
        if self.lock.locked():
            return {"operation": {"status": "busy", "action": action, "phase": "validation", "message": "其他读取或操作进行中", "verified": False}, "snapshot": None}
        await self.lock.acquire()
        self.managing = True
        task = asyncio.create_task(self._operate(action, token))
        self.active = task
        def finished(_):
            self.managing = False
            self.active = None
            self.lock.release()
        task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def _operate(self, action, token):
        def progress(value):
            self.last_operation = {**value, "status": "running", "message": "操作中"}
        try:
            operation = await self.manager.execute(action, token, progress)
        except asyncio.CancelledError:
            self.last_operation = {**(self.last_operation or {}), "status": "uncertain", "verified": False, "message": "不确定：操作被中断，请刷新核对"}
            raise
        except Exception as exc:
            operation = {"status": "uncertain", "action": action, "verified": False, "message": f"不确定：{type(exc).__name__}，请刷新核对"}
        operation["finishedAt"] = datetime.now(timezone.utc).timestamp() * 1000
        self.last_operation = operation
        try:
            snapshot = await self._snapshot()
        except Exception:
            snapshot = None
        if snapshot is None or snapshot["deviceStatus"]["status"] != "ok":
            operation["message"] += "；设备列表刷新失败，请手动刷新"
        return {"operation": operation, "snapshot": snapshot}
