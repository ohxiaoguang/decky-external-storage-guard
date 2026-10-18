"""Decky API v1: diagnostics and explicitly confirmed safe UDisks remounts."""
from pathlib import Path
import sys

# Decky loads main.py in a separate process; make our packaged modules explicit.
plugin_path = str(Path(__file__).resolve().parent)
if plugin_path not in sys.path:
    sys.path.insert(0, plugin_path)

from storage_guard.service import Service


class Plugin:
    def __init__(self):
        self.service = Service()

    async def get_snapshot(self, window: str = "boot") -> dict:
        return await self.service.snapshot(window)

    async def remount_partition(self, token: str) -> dict:
        return await self.service.remount(token)

    async def _main(self):
        pass

    async def _unload(self):
        await self.service.close()

    async def _uninstall(self):
        await self.service.close()
