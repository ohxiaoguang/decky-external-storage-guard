"""Decky API v1: raw journal and safe independent UDisks mount/unmount."""
from pathlib import Path
import sys

# Decky loads main.py in a separate process; make our packaged modules explicit.
plugin_path = str(Path(__file__).resolve().parent)
if plugin_path not in sys.path:
    sys.path.insert(0, plugin_path)

from storage_guard.service import Service
from storage_guard.commands import ReadFailure


class Plugin:
    def __init__(self):
        self.service = Service()

    async def get_snapshot(self) -> dict:
        return await self.service.snapshot()

    async def unmount_partition(self, token: str) -> dict:
        return await self.service.operate("unmount", token)

    async def mount_partition(self, token: str) -> dict:
        return await self.service.operate("mount", token)

    async def get_logs(self) -> dict:
        try:
            return await self.service.logs()
        except ReadFailure as exc:
            return {"status": exc.status, "message": exc.message, "text": "", "limited": False}
        except (OSError, ValueError, TypeError) as exc:
            return {"status": "read_failed", "message": f"日志读取失败：{type(exc).__name__}", "text": "", "limited": False}

    async def _main(self):
        pass

    async def _unload(self):
        await self.service.close()

    async def _uninstall(self):
        await self.service.close()
