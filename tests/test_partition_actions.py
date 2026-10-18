import asyncio
from copy import deepcopy
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch
from storage_guard.commands import Output, ReadFailure
from types import SimpleNamespace
from storage_guard.remount import PartitionManager
from storage_guard.service import Service
from test_remount import managed_device, inventory


class ActionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.device = managed_device()
        self.unmounted = deepcopy(self.device)
        self.unmounted["partitions"][1]["mounts"] = []
        self.manager = PartitionManager()
        self.user = SimpleNamespace(pw_name="gamer", pw_uid=1000, pw_gid=1000, pw_dir="/home/gamer")
        patcher = patch("storage_guard.remount.current_user", return_value=self.user)
        patcher.start()
        self.addCleanup(patcher.stop)

    def grant(self, action, device=None):
        self.manager.decorate([device or (self.device if action == "unmount" else self.unmounted)])
        return next(g for g, v in self.manager.grants.items() if v.action == action)

    async def perform(self, action, scans, output=Output(0, "ok", ""), token=None):
        token = token or self.grant(action)
        with patch("storage_guard.remount.scan", AsyncMock(side_effect=[inventory(d) if d else ([], [], []) for d in scans])), patch(
            "storage_guard.remount.live_check"), patch("storage_guard.remount.run", AsyncMock(side_effect=output if isinstance(output, Exception) else None, return_value=output)) as command:
            result = await self.manager.execute(action, token)
        return result, command

    async def test_unmount_verifies_absence_and_never_mounts_or_powers_off(self):
        result, command = await self.perform("unmount", [self.device, self.unmounted])
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["verified"])
        self.assertEqual(result["mounts"], [])
        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.call_args.args[0], ["udisksctl", "unmount", "-b", "/dev/mmcblk0p1", "--no-user-interaction"])

    async def test_mount_verifies_identity_mountpoint_permissions_and_readonly(self):
        result, command = await self.perform("mount", [self.unmounted, self.device])
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["verified"])
        self.assertEqual(result["mounts"][0]["target"], "/run/media/deck/card")
        self.assertFalse(result["readOnly"])
        self.assertNotIn("user", command.call_args.kwargs)
        self.assertEqual(command.call_args.args[0], ["udisksctl", "mount", "-b", "/dev/mmcblk0p1", "--no-user-interaction"])

    async def test_exit_zero_without_actual_transition_is_uncertain(self):
        for action, scans in (("unmount", [self.device, self.device]), ("mount", [self.unmounted, self.unmounted])):
            self.setUp()
            result, command = await self.perform(action, scans)
            self.assertEqual(result["status"], "uncertain")
            self.assertFalse(result["verified"])
            self.assertEqual(command.call_count, 1)

    async def test_nonzero_busy_permission_missing_device_do_not_report_success(self):
        for detail, expected in (("Device busy", "device_busy"), ("Not authorized", "permission_denied"), ("No such device", "device_disconnected"), ("bad superblock", "unmount_failed")):
            self.setUp()
            result, command = await self.perform("unmount", [self.device], Output(1, "stdout", detail))
            self.assertEqual(result["status"], expected)
            self.assertFalse(result["verified"])
            self.assertEqual(command.call_count, 1)
            self.assertIn(detail, result["message"])
            self.assertEqual(result["returncode"], 1)

    async def test_mount_failure_checks_stdout_and_stderr(self):
        result, command = await self.perform("mount", [self.unmounted], Output(1, "mount failed", "bad superblock"))
        self.assertEqual(result["status"], "mount_failed")
        self.assertEqual(result["stderr"], "bad superblock")
        self.assertEqual(result["stdout"], "mount failed")
        self.assertFalse(result["verified"])

    async def test_timeout_is_uncertain_and_no_retry(self):
        result, command = await self.perform("unmount", [self.device], ReadFailure("timeout", "timeout"))
        self.assertEqual(result["status"], "uncertain")
        self.assertIsNone(result["returncode"])
        self.assertEqual(command.call_count, 1)

    async def test_disconnect_before_command_and_during_verification(self):
        result, command = await self.perform("unmount", [None])
        self.assertEqual(result["status"], "device_disconnected")
        command.assert_not_called()
        self.setUp()
        result, command = await self.perform("unmount", [self.device, None])
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(command.call_count, 1)

    async def test_arbitrary_paths_expiry_replay_and_wrong_action_never_execute(self):
        with patch("storage_guard.remount.run", AsyncMock()) as command:
            for token in ("/dev/nvme0n1p1", {"path": "/dev/sda1"}, None):
                self.assertEqual((await self.manager.execute("unmount", token))["status"], "invalid_target")
            token = self.grant("unmount")
            self.assertEqual((await self.manager.execute("mount", token))["status"], "invalid_target")
            self.manager.grants[token].expires = 0
            self.assertEqual((await self.manager.execute("unmount", token))["status"], "invalid_target")
            command.assert_not_called()
        self.setUp()
        token = self.grant("unmount")
        await self.perform("unmount", [self.device, self.unmounted], token=token)
        with patch("storage_guard.remount.run", AsyncMock()) as command:
            self.assertEqual((await self.manager.execute("unmount", token))["status"], "invalid_target")
            command.assert_not_called()

    async def test_replacement_wrong_partition_and_system_mount_stop_before_command(self):
        for change in ("uuid", "partitionUuid", "majorMinor", "diskseq", "system", "partition", "topology"):
            self.setUp()
            changed = deepcopy(self.device)
            part = changed["partitions"][1]
            if change == "diskseq": changed["sysfs"]["diskseq"] = "99"
            elif change == "system": part["mounts"][0]["target"] = "/home"
            elif change == "partition": part["path"] = "/dev/mmcblk0p2"
            elif change == "topology": changed["topology"] = "/sys/nvme/nvme0n1"
            else: part[change] = "different"
            result, command = await self.perform("unmount", [changed])
            self.assertNotEqual(result["status"], "success")
            command.assert_not_called()

    async def test_mount_does_not_run_if_partition_became_mounted_after_grant(self):
        result, command = await self.perform("mount", [self.device])
        self.assertEqual(result["status"], "stale_target")
        command.assert_not_called()

    async def test_action_button_grants_invert_after_verified_unmount(self):
        self.manager.decorate([self.device])
        actions = self.device["partitions"][1]["actions"]
        self.assertTrue(actions["unmount"]["token"])
        self.assertIsNone(actions["mount"]["token"])
        self.manager.decorate([self.unmounted])
        actions = self.unmounted["partitions"][1]["actions"]
        self.assertTrue(actions["mount"]["token"])
        self.assertIsNone(actions["unmount"]["token"])
        self.assertIsNone(self.unmounted["partitions"][0]["actions"]["mount"]["token"])

    async def test_current_ro_and_preserved_ro_are_never_forced_rw(self):
        self.device["partitions"][1]["mounts"][0]["readOnly"] = True
        result, _ = await self.perform("unmount", [self.device, self.unmounted])
        self.assertEqual(result["status"], "success")
        final = deepcopy(self.device)
        result, command = await self.perform("mount", [self.unmounted, final])
        self.assertEqual(result["status"], "success")
        self.assertIn("ro", command.call_args.args[0][-1].split(","))
        self.assertNotIn("rw", command.call_args.args[0][-1].split(","))

    async def test_requested_ro_not_observed_is_uncertain(self):
        self.unmounted["partitions"][1]["readOnly"] = True
        result, command = await self.perform("mount", [self.unmounted, self.device])
        self.assertEqual(result["status"], "uncertain")
        self.assertIn("ro", command.call_args.args[0][-1].split(","))

    async def test_nonlinux_fresh_mount_uses_verified_desktop_uid_gid_or_refuses(self):
        self.unmounted["partitions"][1]["filesystem"] = "exfat"
        token = self.grant("mount")
        self.assertEqual(self.manager.grants[token].options, ["nosuid", "nodev", "uid=1000", "gid=1000"])
        with patch("storage_guard.remount.current_user", side_effect=ReadFailure("unsupported_permissions", "unknown user")):
            self.manager.decorate([self.unmounted])
            self.assertIsNone(self.unmounted["partitions"][1]["actions"]["mount"]["token"])

    async def test_preserved_nonlinux_options_bound_to_verified_connection_and_ro(self):
        self.device["partitions"][1]["filesystem"] = "exfat"
        self.device["partitions"][1]["mounts"][0]["filesystem"] = "exfat"
        self.device["partitions"][1]["mounts"][0].update(options="ro,nosuid,nodev,uid=1000,gid=1000,fmask=0022", readOnly=True)
        self.unmounted = deepcopy(self.device)
        self.unmounted["partitions"][1]["mounts"] = []
        result, _ = await self.perform("unmount", [self.device, self.unmounted])
        self.assertEqual(result["status"], "success")
        result, command = await self.perform("mount", [self.unmounted, self.device])
        self.assertEqual(result["status"], "success")
        for flag in ("ro", "nosuid", "nodev", "uid=1000", "gid=1000", "fmask=0022"):
            self.assertIn(flag, command.call_args.args[0][-1].split(","))
        changed = deepcopy(self.unmounted)
        changed["sysfs"]["diskseq"] = "different"
        with patch("storage_guard.remount.current_user", side_effect=ReadFailure("unsupported_permissions", "no desktop identity")):
            self.manager.decorate([changed])
            self.assertIsNone(changed["partitions"][1]["actions"]["mount"]["token"])

    async def test_mount_identity_change_after_zero_exit_cannot_be_success(self):
        changed = deepcopy(self.device)
        changed["sysfs"]["diskseq"] = "100"
        result, command = await self.perform("mount", [self.unmounted, changed])
        self.assertEqual(result["status"], "uncertain")
        self.assertFalse(result["verified"])
        self.assertEqual(command.call_count, 1)

    async def test_mount_unknown_user_never_gets_grant_even_with_cached_ext4_options(self):
        await self.perform("unmount", [self.device, self.unmounted])
        for filesystem in ("ext4", "exfat", "ntfs"):
            self.unmounted["partitions"][1]["filesystem"] = filesystem
            with patch("storage_guard.remount.current_user", side_effect=ReadFailure("unsupported_permissions", "无法确认桌面用户")):
                self.manager.decorate([self.unmounted])
            self.assertIsNone(self.unmounted["partitions"][1]["actions"]["mount"]["token"])

    async def test_untrusted_process_after_grant_never_executes_either_action(self):
        for action, device in (("mount", self.unmounted), ("unmount", self.device)):
            token = self.grant(action)
            with patch("storage_guard.remount.current_user", side_effect=ReadFailure("permission_denied", "untrusted process")):
                result, command = await self.perform(action, [device], token=token)
            self.assertFalse(result["verified"])
            command.assert_not_called()

    async def test_wrong_root_mount_path_is_uncertain_without_additional_device_changes(self):
        final = deepcopy(self.device)
        final["partitions"][1]["mounts"][0]["target"] = "/run/media/root/SN512"
        result, command = await self.perform("mount", [self.unmounted, final])
        self.assertEqual(result["status"], "uncertain")
        self.assertFalse(result["verified"])
        self.assertIn("root 用户目录", result["message"])
        self.assertEqual(command.call_count, 1)
        self.assertNotIn("user", command.call_args.kwargs)

    async def test_user_mount_preserves_custom_paths_on_sd_and_usb(self):
        for usb, target in ((False, "/run/media/gamer/SN512"), (False, "/mnt/My Games"), (True, "/media/USB SSD")):
            self.device = managed_device(usb)
            self.device["partitions"][1]["mounts"][0]["target"] = target
            self.unmounted = deepcopy(self.device)
            self.unmounted["partitions"][1]["mounts"] = []
            result, command = await self.perform("mount", [self.unmounted, self.device])
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["mounts"][0]["target"], target)
            self.assertNotIn("user", command.call_args.kwargs)
            self.assertNotIn(target, command.call_args.args[0])

    async def test_user_mount_authorization_denial_stops_without_root_retry(self):
        result, command = await self.perform("mount", [self.unmounted], Output(1, "", "Not authorized to perform operation"))
        self.assertEqual(result["status"], "permission_denied")
        self.assertFalse(result["verified"])
        self.assertEqual(result["returncode"], 1)
        self.assertEqual(command.call_count, 1)
        self.assertNotIn("user", command.call_args.kwargs)

    async def test_wrong_mount_filesystem_after_command_is_uncertain(self):
        final = deepcopy(self.device)
        final["partitions"][1]["mounts"][0]["filesystem"] = "vfat"
        result, command = await self.perform("mount", [self.unmounted, final])
        self.assertEqual(result["status"], "uncertain")
        self.assertFalse(result["verified"])
        self.assertIn("文件系统类型", result["message"])

    async def test_both_buttons_disabled_when_current_process_is_not_trusted(self):
        for device in (self.device, self.unmounted):
            with patch("storage_guard.remount.current_user", side_effect=ReadFailure("permission_denied", "untrusted process")):
                self.manager.decorate([device])
            for action in ("mount", "unmount"):
                self.assertIsNone(device["partitions"][1]["actions"][action]["token"])



class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_refresh_returns_explicit_status_and_does_not_destroy_result(self):
        service = Service()
        with patch.object(service.manager, "execute", AsyncMock(return_value={"status": "device_busy", "message": "设备正在使用", "verified": False})), patch(
            "storage_guard.service.scan", AsyncMock(side_effect=ReadFailure("timeout", "timeout"))):
            result = await service.operate("unmount", "token")
        self.assertEqual(result["operation"]["status"], "device_busy")
        self.assertEqual(result["snapshot"]["deviceStatus"]["status"], "timeout")
        await service.close()

    async def test_canceled_rpc_and_unload_waiter_do_not_cancel_command(self):
        service = Service()
        started, finish = asyncio.Event(), asyncio.Event()
        async def slow(action, token, progress):
            progress({"status": "running", "action": action, "message": "操作中"})
            started.set()
            await finish.wait()
            return {"status": "success", "message": "已卸载", "verified": True}
        with patch.object(service.manager, "execute", slow), patch.object(service, "_snapshot", AsyncMock(return_value={"deviceStatus": {"status": "ok"}})):
            client = asyncio.create_task(service.operate("unmount", "token"))
            await started.wait()
            self.assertEqual((await service.operate("mount", "token"))["operation"]["status"], "busy")
            transaction = service.active
            client.cancel()
            with self.assertRaises(asyncio.CancelledError): await client
            closer = asyncio.create_task(service.close())
            await asyncio.sleep(0)
            closer.cancel()
            with self.assertRaises(asyncio.CancelledError): await closer
            self.assertFalse(transaction.done())
            finish.set(); await transaction
            self.assertTrue(service.last_operation["verified"])
        await service.close()

    async def test_no_persistent_files_or_history(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"DECKY_PLUGIN_RUNTIME_DIR": directory}):
            service = Service()
            with patch.object(service.manager, "execute", AsyncMock(side_effect=lambda *args: {"status": "success", "message": "已卸载", "verified": True})), patch.object(
                service, "_snapshot", AsyncMock(return_value={"deviceStatus": {"status": "ok"}})):
                await service.operate("unmount", "one")
                first = service.last_operation
                await service.operate("mount", "two")
                self.assertIsNot(first, service.last_operation)
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertIsNone(Service().last_operation)
            await service.close()

    async def test_entrypoint_only_exposes_separate_operations_and_raw_logs(self):
        from main import Plugin
        plugin = Plugin()
        with patch.object(plugin.service, "operate", AsyncMock(return_value={})) as command:
            await plugin.unmount_partition("one")
            await plugin.mount_partition("two")
        self.assertEqual([c.args for c in command.call_args_list], [("unmount", "one"), ("mount", "two")])
        self.assertFalse(hasattr(plugin, "remount_partition"))
        with patch.object(plugin.service, "logs", AsyncMock(side_effect=ReadFailure("permission_denied", "无权限"))):
            self.assertEqual((await plugin.get_logs())["status"], "permission_denied")
        await plugin._unload()

    async def test_forced_action_cancellation_is_explicitly_uncertain(self):
        service = Service()
        started = asyncio.Event()
        async def blocked(action, token, progress):
            progress({"action": action, "status": "running", "message": "操作中"})
            started.set()
            await asyncio.Event().wait()
        with patch.object(service.manager, "execute", blocked):
            client = asyncio.create_task(service.operate("mount", "token"))
            await started.wait()
            service.active.cancel()
            with self.assertRaises(asyncio.CancelledError): await client
            self.assertEqual(service.last_operation["status"], "uncertain")
            self.assertFalse(service.last_operation["verified"])
        await service.close()

    async def test_snapshot_cancellation_on_unload_does_not_start_any_operation(self):
        service = Service()
        started = asyncio.Event()
        async def slow():
            started.set()
            await asyncio.Event().wait()
        with patch("storage_guard.service.scan", slow), patch.object(service.manager, "execute", AsyncMock()) as command:
            request = asyncio.create_task(service.snapshot())
            await started.wait()
            await service.close()
            with self.assertRaises(asyncio.CancelledError): await request
            command.assert_not_called()
