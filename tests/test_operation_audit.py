import json
import os
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from main import Plugin
from storage_guard.commands import Output, ReadFailure
from storage_guard.operation_store import AuditStore
from storage_guard.service import Service
from storage_guard.report import build_report
from test_remount import managed_device, inventory, clean_journal
from test_report import report_fixture, HARDWARE


class AuditTests(unittest.TestCase):
    def operation(self, number=0):
        return {"operationId": f"{number:024x}", "bootId": "a" * 32, "status": "running", "phase": "unmount",
                "startedAt": 1000, "partition": "/dev/mmcblk0p1", "method": "udisksctl unmount + mount",
                "commands": [{"stdout": "mounted /run/media/alice/private", "stderr": 'password="secret value"'}]}

    def test_history_upserts_by_stable_id_and_is_private_bounded(self):
        with TemporaryDirectory() as directory:
            store = AuditStore(directory)
            store.MAX_OPERATIONS = 2
            for number in range(3):
                op = self.operation(number)
                store.record(op)
                store.record({**op, "status": "success"})
            data = store.load()
            self.assertEqual(len(data["operations"]), 2)
            self.assertTrue(data["limited"])
            self.assertEqual(data["operations"][-1]["operationId"], self.operation(2)["operationId"])
            self.assertEqual(data["operations"][-1]["bootId"], "a" * 32)
            self.assertTrue(all(op["status"] == "success" for op in data["operations"]))
            text = store.path.read_text()
            self.assertNotIn("secret value", text)
            self.assertNotIn("/run/media/alice", text)
            self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)

    def test_missing_runtime_corrupt_and_symlink_audit_fail_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            store = AuditStore()
            self.assertEqual(store.load()["status"], "unavailable")
            with self.assertRaises(OSError):
                store.record(self.operation())
        with TemporaryDirectory() as directory:
            store = AuditStore(directory)
            store.path.write_text("invalid json")
            with self.assertRaises(OSError):
                store.record(self.operation())
            self.assertEqual(store.path.read_text(), "invalid json")
            store.path.unlink()
            target = Path(directory) / "other"
            target.write_text("private")
            store.path.symlink_to(target)
            with self.assertRaises(OSError):
                store.record(self.operation())
            self.assertEqual(target.read_text(), "private")

    def test_report_includes_audit_results_outputs_and_limits_with_no_kernel_logs(self):
        snapshot, capture = report_fixture()
        capture["audit"] = {"status": "ok", "message": "audit", "limited": True, "operations": [
            {**self.operation(), "commands": [{"returncode": 1, "stdout": "not done", "stderr": "Device busy token=private"}],
             "status": "device_busy", "detail": "unmount failed"}]}
        result = build_report(snapshot, capture, HARDWARE)
        self.assertIn("独立操作审计", result["text"])
        self.assertIn('"returncode": 1', result["text"])
        self.assertIn("Device busy", result["text"])
        self.assertNotIn("token=private", result["text"])
        self.assertIn("历史已截断", result["text"])
        # Audit JSON remains parseable even when output contains credentials/quotes.
        line = next(line for line in result["text"].splitlines() if '"operationId"' in line)
        self.assertEqual(json.loads(line)["bootId"], "a" * 32)


class ServiceAuditTests(unittest.IsolatedAsyncioTestCase):
    async def perform(self, scans, outputs=None, audit_failure=False):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        with patch.dict(os.environ, {"DECKY_PLUGIN_RUNTIME_DIR": directory.name}):
            service = Service()
        self.addAsyncCleanup(service.close)
        device = managed_device()
        service.remounter.decorate([device], [], "current", True)
        token = device["partitions"][1]["management"]["token"]
        with patch("storage_guard.service.boot_id", return_value="current"), patch("storage_guard.remount.scan", AsyncMock(side_effect=[inventory(d) for d in scans])), patch(
            "storage_guard.remount.live_check"), patch("storage_guard.remount.read_journal", AsyncMock(return_value=clean_journal())), patch(
            "storage_guard.remount.run", AsyncMock(side_effect=outputs or [Output(0, "unmounted", "warning"), Output(0, "mounted", "")])) as command, patch.object(
            service, "_snapshot", AsyncMock(return_value={"realRefresh": True})) as refresh:
            if audit_failure:
                service.audit_store.record = lambda operation: (_ for _ in ()).throw(OSError("no space"))
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
        history = service.audit_store.load()["operations"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["status"], "success")
        self.assertEqual([entry["returncode"] for entry in history[0]["commands"]], [0, 0])
        self.assertEqual(history[0]["commands"][0]["stderr"], "warning")
        self.assertIn("finishedAt", history[0])

    async def test_zero_exit_without_unmount_or_mount_is_never_success(self):
        device = managed_device()
        unmounted = deepcopy(device)
        unmounted["partitions"][1]["mounts"] = []
        result, command, service = await self.perform([device, device, device])
        self.assertNotEqual(result["status"], "success")
        self.assertIsNone(result["unmounted"])
        self.assertIsNone(result["afterUnmount"])
        self.assertEqual(command.call_count, 1)
        self.assertNotEqual(service.audit_store.load()["operations"][-1]["status"], "success")
        result, command, _ = await self.perform([device, device, unmounted, unmounted])
        self.assertNotEqual(result["status"], "success")
        self.assertIsNone(result["mounted"])
        self.assertEqual(command.call_count, 2)

    async def test_busy_stops_after_unmount_and_audits_both_output_streams(self):
        device = managed_device()
        result, command, service = await self.perform([device, device], [Output(1, "udisks stdout", "Device busy")])
        self.assertEqual(result["status"], "device_busy")
        self.assertEqual(command.call_count, 1)
        audit = service.audit_store.load()["operations"][0]
        self.assertEqual(audit["commands"][0]["stdout"], "udisks stdout")
        self.assertEqual(audit["commands"][0]["stderr"], "Device busy")
        self.assertEqual(audit["commands"][0]["returncode"], 1)
        self.assertIn("Device busy", audit["detail"])

    async def test_no_audit_write_means_no_device_command(self):
        result, command, _ = await self.perform([], audit_failure=True)
        self.assertEqual(result["status"], "audit_write_failed")
        command.assert_not_called()

    async def test_timeout_audited_as_unknown_and_does_not_mount(self):
        device = managed_device()
        result, command, service = await self.perform([device, device], [ReadFailure("timeout", "timeout")])
        self.assertEqual(result["status"], "timeout")
        self.assertIsNone(result["unmounted"])
        self.assertEqual(command.call_count, 1)
        entry = service.audit_store.load()["operations"][0]["commands"][0]
        self.assertIsNone(entry["returncode"])
        self.assertEqual(entry["status"], "timeout")

    async def test_plugin_remount_rpc_forwards_token_not_a_refresh(self):
        plugin = Plugin()
        self.addAsyncCleanup(plugin.service.close)
        with patch.object(plugin.service, "remount", AsyncMock(return_value={"operation": "result"})) as remount, patch.object(plugin.service, "snapshot", AsyncMock()) as refresh:
            self.assertEqual(await plugin.remount_partition("issued-token"), {"operation": "result"})
            remount.assert_awaited_once_with("issued-token")
            refresh.assert_not_called()

    async def test_report_audit_range_is_boot_isolated_and_historical_time_limited(self):
        service = Service()
        self.addAsyncCleanup(service.close)
        snapshot, original = report_fixture()
        async def capture_snapshot(window, capture, management):
            self.assertFalse(management)
            capture.update(original)
            return {**snapshot, "window": window}
        operations = [{"operationId": "one", "bootId": "current", "startedAt": 99_000_000, "detail": "current-operation"},
                      {"operationId": "two", "bootId": "other", "startedAt": 99_000_000, "detail": "other-boot-operation"},
                      {"operationId": "three", "bootId": "old", "startedAt": 1, "detail": "old-operation"}]
        from datetime import datetime as real_datetime
        from datetime import timezone
        with patch.object(service, "_snapshot", capture_snapshot), patch.object(service.audit_store, "load", return_value={"status": "ok", "message": "audit", "operations": operations}), patch(
            "storage_guard.service.boot_id", return_value="current"), patch("storage_guard.service.enrich_readers", AsyncMock()), patch(
            "storage_guard.service.private_identifiers", return_value=[]), patch("storage_guard.service.datetime") as clock:
            clock.now.return_value = real_datetime.fromtimestamp(100000, timezone.utc)
            boot = await service.generate_report("boot")
            self.assertIn("current-operation", boot["text"])
            self.assertNotIn("other-boot-operation", boot["text"])
            self.assertNotIn("old-operation", boot["text"])
            # Reset because filtering uses a fresh load in production.
            service.audit_store.load.return_value = {"status": "ok", "message": "audit", "operations": operations}
            day = await service.generate_report("day")
            self.assertNotIn("old-operation", day["text"])
            self.assertIn("other-boot-operation", day["text"])
            service.audit_store.load.return_value = {"status": "ok", "message": "audit", "operations": operations}
            all_records = await service.generate_report("all")
            self.assertIn("old-operation", all_records["text"])
