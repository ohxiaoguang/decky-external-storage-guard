import asyncio
import os
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch
from main import Plugin
from storage_guard.commands import Output, ReadFailure
from storage_guard.service import Service
from storage_guard.report import build_report
from test_remount import managed_device, inventory, clean_journal
from test_report import report_fixture, HARDWARE

class SessionOperationTests(unittest.IsolatedAsyncioTestCase):
    async def perform(self, scans, outputs=None):
        service = Service()
        self.addAsyncCleanup(service.close)
        device = managed_device()
        service.remounter.decorate([device], [], "current", True)
        token = device["partitions"][1]["management"]["token"]
        with patch("storage_guard.service.boot_id", return_value="current"), patch("storage_guard.remount.scan", AsyncMock(side_effect=[inventory(d) for d in scans])), patch(
            "storage_guard.remount.live_check"), patch("storage_guard.remount.read_journal", AsyncMock(return_value=clean_journal())), patch(
            "storage_guard.remount.run", AsyncMock(side_effect=outputs or [Output(0, "unmounted", "warning"), Output(0, "mounted", "")])) as command, patch.object(
            service, "_snapshot", AsyncMock(return_value={"realRefresh": True})) as refresh:
            result = await service.remount(token)
        self.assertEqual(result["snapshot"], {"realRefresh": True})
        refresh.assert_awaited_once_with("boot")
        return result["operation"], command, service

    async def test_no_kernel_ext4_records_needed_but_all_three_mount_states_required(self):
        device = managed_device()
        unmounted = deepcopy(device)
        unmounted["partitions"][1]["mounts"] = []
        result, command, service = await self.perform([device, device, unmounted, device])
        self.assertEqual(result["status"], "success")
        self.assertEqual(command.call_count, 2)
        self.assertTrue(result["beforeUnmount"]["mounts"])
        self.assertFalse(result["afterUnmount"]["mounts"])
        self.assertTrue(result["afterMount"]["mounts"])
        self.assertIs(service.last_operation, result)
        self.assertEqual([entry["returncode"] for entry in result["commands"]], [0, 0])
        self.assertEqual(result["commands"][0]["stderr"], "warning")

    async def test_zero_exit_without_unmount_or_mount_is_never_success(self):
        device = managed_device()
        unmounted = deepcopy(device)
        unmounted["partitions"][1]["mounts"] = []
        result, command, service = await self.perform([device, device, device])
        self.assertNotEqual(result["status"], "success")
        self.assertIsNone(result["unmounted"])
        self.assertIsNone(result["afterUnmount"])
        self.assertEqual(command.call_count, 1)
        self.assertNotEqual(service.last_operation["status"], "success")
        result, command, _ = await self.perform([device, device, unmounted, unmounted])
        self.assertNotEqual(result["status"], "success")
        self.assertIsNone(result["mounted"])
        self.assertEqual(command.call_count, 2)

    async def test_busy_stops_after_unmount_and_returns_both_output_streams(self):
        device = managed_device()
        result, command, service = await self.perform([device, device], [Output(1, "udisks stdout", "Device busy")])
        self.assertEqual(result["status"], "device_busy")
        self.assertEqual(command.call_count, 1)
        operation = service.last_operation
        self.assertEqual(operation["commands"][0]["stdout"], "udisks stdout")
        self.assertEqual(operation["commands"][0]["stderr"], "Device busy")
        self.assertEqual(operation["commands"][0]["returncode"], 1)
        self.assertIn("Device busy", operation["detail"])

    async def test_timeout_is_unknown_and_does_not_mount(self):
        device = managed_device()
        result, command, service = await self.perform([device, device], [ReadFailure("timeout", "timeout")])
        self.assertEqual(result["status"], "timeout")
        self.assertIsNone(result["unmounted"])
        self.assertEqual(command.call_count, 1)
        entry = service.last_operation["commands"][0]
        self.assertIsNone(entry["returncode"])
        self.assertEqual(entry["status"], "timeout")

    async def test_plugin_remount_rpc_forwards_token_not_a_refresh(self):
        plugin = Plugin()
        self.addAsyncCleanup(plugin.service.close)
        with patch.object(plugin.service, "remount", AsyncMock(return_value={"operation": "result"})) as remount, patch.object(plugin.service, "snapshot", AsyncMock()) as refresh:
            self.assertEqual(await plugin.remount_partition("issued-token"), {"operation": "result"})
            remount.assert_awaited_once_with("issued-token")
            refresh.assert_not_called()


    async def test_no_persistent_files_and_only_latest_result_survives_in_session(self):
        device = managed_device()
        unmounted = deepcopy(device)
        unmounted["partitions"][1]["mounts"] = []
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"DECKY_PLUGIN_RUNTIME_DIR": directory}):
            result, _, service = await self.perform([device, device, unmounted, device])
            self.assertEqual(result["status"], "success")
            self.assertEqual(list(Path(directory).iterdir()), [])
            with patch.object(service, "_snapshot", AsyncMock(return_value={})):
                second = await service.remount("already-consumed-token")
            self.assertEqual(service.last_operation["status"], "invalid_target")
            self.assertIs(service.last_operation, second["operation"])
            self.assertEqual(list(Path(directory).iterdir()), [])
            fresh_service = Service()
            self.assertIsNone(fresh_service.last_operation)
            await fresh_service.close()

    async def test_cancel_rpc_and_cancel_unload_waiter_during_mount_does_not_cancel_transaction(self):
        service = Service()
        self.addAsyncCleanup(service.close)
        device = managed_device()
        unmounted = deepcopy(device)
        unmounted["partitions"][1]["mounts"] = []
        service.remounter.decorate([device], [], "current", True)
        token = device["partitions"][1]["management"]["token"]
        mounting, finish = asyncio.Event(), asyncio.Event()
        async def command(argv, **kwargs):
            if argv[1] == "mount":
                mounting.set()
                await finish.wait()
            return Output(0, "ok", "")
        with patch("storage_guard.remount.scan", AsyncMock(side_effect=[inventory(d) for d in [device, device, unmounted, device]])), patch(
            "storage_guard.remount.live_check"), patch("storage_guard.remount.read_journal", AsyncMock(return_value=clean_journal())), patch(
            "storage_guard.remount.run", command), patch.object(service, "_snapshot", AsyncMock(return_value={})):
            client = asyncio.create_task(service.remount(token))
            await mounting.wait()
            transaction = service.active
            client.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await client
            closer = asyncio.create_task(service.close())
            await asyncio.sleep(0)
            closer.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await closer
            self.assertFalse(transaction.done())
            finish.set()
            await transaction
            self.assertEqual(service.last_operation["status"], "success")
            self.assertTrue(service.last_operation["unmounted"])
            self.assertTrue(service.last_operation["mounted"])

    async def test_forced_transaction_cancellation_keeps_explicit_uncertain_result(self):
        service = Service()
        started = asyncio.Event()
        async def blocked(token, boot, progress):
            progress({"status": "running", "phase": "mount", "unmounted": True, "warnings": [], "partition": "/dev/mmcblk0p1"})
            started.set()
            await asyncio.Event().wait()
        with patch.object(service.remounter, "execute", blocked):
            client = asyncio.create_task(service.remount("token"))
            await started.wait()
            service.active.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await client
            self.assertEqual(service.last_operation["status"], "interrupted")
            self.assertIsNone(service.last_operation["mounted"])
            self.assertTrue(service.last_operation["unmounted"])
        await service.close()

    async def test_refresh_failure_preserves_verified_result_instead_of_losing_it(self):
        service = Service()
        with patch.object(service.remounter, "execute", AsyncMock(return_value={"status": "success", "warnings": []})), patch.object(
            service, "_snapshot", AsyncMock(side_effect=OSError("snapshot failed"))):
            result = await service.remount("token")
            self.assertIsNone(result["snapshot"])
            self.assertEqual(service.last_operation["status"], "success")
            self.assertIn("最终状态刷新失败", result["operation"]["warnings"][0])
        await service.close()

    async def test_report_contains_only_last_session_result_and_original_kernel_logs(self):
        snapshot, capture = report_fixture()
        capture["operation"] = {"status": "mount_failed", "phase": "mount", "detail": "bad superblock token=private", "commands": [{"returncode": 1}]}
        report = build_report(snapshot, capture, HARDWARE)
        self.assertIn("当前会话最近一次", report["text"])
        self.assertIn('"returncode": 1', report["text"])
        self.assertIn("完整原始诊断消息", report["text"])
        self.assertNotIn("token=private", report["text"])
        self.assertNotIn("独立操作审计", report["text"])
        capture["operation"] = None
        self.assertIn("当前会话没有操作结果", build_report(snapshot, capture, HARDWARE)["text"])
