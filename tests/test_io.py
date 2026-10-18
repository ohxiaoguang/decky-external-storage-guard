import asyncio
import json
import sys
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from storage_guard.commands import run, require_success, Output, ReadFailure


class IOTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # These tests isolate bounded I/O. A separate process tests real non-root identity.
        patcher = patch("storage_guard.commands.current_user", return_value=SimpleNamespace(pw_name="tester", pw_dir="/tmp"))
        patcher.start(); self.addCleanup(patcher.stop)

    async def test_subprocess_success(self):
        output = await run([sys.executable, "-c", "print('ok')"])
        self.assertEqual(require_success(output, "test"), "ok\n")

    async def test_missing_command(self):
        with self.assertRaises(ReadFailure) as caught:
            await run(["/no/such/storage/command"])
        self.assertEqual(caught.exception.status, "missing_command")

    async def test_subprocess_timeout_and_output_cap(self):
        for script, options, status in [
            ("import time; time.sleep(10)", {"timeout": 0.05}, "timeout"),
            ("print('x'*10000)", {"limit": 100}, "output_limit"),
        ]:
            with self.subTest(status=status), self.assertRaises(ReadFailure) as caught:
                await run([sys.executable, "-c", script], **options)
            self.assertEqual(caught.exception.status, status)

    async def test_cancellation_terminates_subprocess(self):
        with TemporaryDirectory() as directory:
            pidfile = Path(directory) / "pid"
            task = asyncio.create_task(run([sys.executable, "-c",
                "import os, pathlib, sys, time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(10)", str(pidfile)]))
            try:
                for _ in range(100):
                    if pidfile.exists():
                        break
                    await asyncio.sleep(0.01)
                self.assertTrue(pidfile.exists())
                pid = int(pidfile.read_text())
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
