import asyncio
import json
import sys
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch
from storage_guard.commands import run, require_success, Output, ReadFailure
from storage_guard.journal import read_journal
from storage_guard.service import Service
from helpers import sd_device, record


class IOTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_permission_warning_with_success_exit_is_not_clean(self):
        for output in [Output(1, "", "Permission denied"), Output(0, "", "Hint: You are currently not seeing messages from other users and the system.")]:
            with patch("storage_guard.journal.run", AsyncMock(return_value=output)):
                with self.assertRaises(ReadFailure) as caught:
                    await read_journal("boot")
            self.assertEqual(caught.exception.status, "permission_denied")

    async def test_previous_boot_not_retained(self):
        for output in [Output(1, "", "Data from the specified boot (-1) is not available: No such boot ID"), Output(0, "", "")]:
            with patch("storage_guard.journal.run", AsyncMock(return_value=output)):
                self.assertEqual((await read_journal("previous"))["status"], "no_history")

    async def test_permissions_take_precedence_over_missing_history(self):
        with patch("storage_guard.journal.run", AsyncMock(return_value=Output(1, "", "Permission denied; no such boot"))):
            with self.assertRaises(ReadFailure) as caught:
                await read_journal("previous")
        self.assertEqual(caught.exception.status, "permission_denied")

    async def test_no_logs_different_from_no_errors(self):
        with patch("storage_guard.journal.run", AsyncMock(return_value=Output(0, "", ""))):
            self.assertEqual((await read_journal("boot"))["status"], "no_logs")

    async def test_bad_json_and_nonzero_exit(self):
        for output in [Output(0, "{bad json", ""), Output(1, "", "journal corrupt")]:
            with patch("storage_guard.journal.run", AsyncMock(return_value=output)), self.assertRaises(ReadFailure) as caught:
                await read_journal("boot")
            self.assertEqual(caught.exception.status, "read_failed")

    async def test_fixed_windows_and_message_length(self):
        mock = AsyncMock(return_value=Output(0, json.dumps(record("x" * 8000)), ""))
        with patch("storage_guard.journal.run", mock):
            result = await read_journal("day")
        self.assertIn("--since=-24h", mock.call_args.args[0])
        self.assertIn("_TRANSPORT=kernel", mock.call_args.args[0])
        self.assertNotIn("--dmesg", mock.call_args.args[0])
        self.assertEqual(len(result["records"][0]["MESSAGE"]), 4096)
        with self.assertRaises(ReadFailure):
            await read_journal("boot;rm -rf /")

    async def test_backend_permission_response(self):
        with patch("storage_guard.service.scan", AsyncMock(return_value=([sd_device()], [], []))), patch(
            "storage_guard.service.read_journal", AsyncMock(side_effect=ReadFailure("permission_denied", "无权限"))):
            result = await Service().snapshot()
        self.assertEqual(result["journalStatus"]["status"], "permission_denied")
        self.assertEqual(result["deviceStatus"]["status"], "ok")
        self.assertEqual(result["events"], [])

    async def test_device_failure_is_not_empty_success(self):
        with patch("storage_guard.service.scan", AsyncMock(side_effect=ReadFailure("timeout", "超时"))), patch(
            "storage_guard.service.read_journal", AsyncMock(return_value={"status": "ok", "message": "ok", "records": [record("I/O error, dev sda")], "limited": False})):
            result = await Service().snapshot()
        self.assertEqual(result["deviceStatus"]["status"], "timeout")
        self.assertIsNone(result["events"][0]["deviceId"])

    async def test_unload_cancels_inflight_work_and_no_polling(self):
        service = Service()
        started = asyncio.Event()
        async def slow_scan():
            started.set()
            await asyncio.Event().wait()
        with patch("storage_guard.service.scan", slow_scan):
            task = asyncio.create_task(service.snapshot())
            await started.wait()
            await service.close()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNone(service.active)
        with self.assertRaises(RuntimeError):
            await service.snapshot()

    async def test_decky_entrypoint_lifecycle_and_serialization(self):
        from main import Plugin
        plugin = Plugin()
        await plugin._main()
        with patch("storage_guard.service.scan", AsyncMock(return_value=([], [], []))), patch(
            "storage_guard.service.read_journal", AsyncMock(return_value={"status": "ok", "message": "ok", "records": [], "limited": False})):
            result = await plugin.get_snapshot("boot")
        json.dumps(result, allow_nan=False)
        await plugin._unload()
        await plugin._uninstall()
