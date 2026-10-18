import asyncio
from copy import deepcopy
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from helpers import node, record
from storage_guard.commands import Output, ReadFailure
from storage_guard.devices import discover
from storage_guard.remount import Remounter, eligibility, filesystem_warnings, live_check, mount_options
from storage_guard.service import Service


def managed_device(usb=False):
    name, partname = ("sda", "sda1") if usb else ("mmcblk0", "mmcblk0p1")
    number, partnumber = ("8:0", "8:1") if usb else ("179:0", "179:1")
    topology = ("/sys/devices/pci/usb2/2-1/2-1:1.0/host6/6:0:0:0/block/sda" if usb else
                "/sys/devices/pci/mmc_host/mmc0/mmc0:aaaa/block/mmcblk0")
    facts = {name: {"topology": topology, "card_type": "" if usb else "SD", "diskseq": "42", "dev": number, "holders": []},
             partname: {"topology": f"{topology}/{partname}", "partition": "1", "dev": partnumber, "holders": []}}
    disk = node(name, tran="usb" if usb else None, **{"maj:min": number}, children=[
        node(partname, type="part", fstype="ext4", uuid="filesystem-uuid", partuuid="partition-uuid", parttype="0x83", **{"maj:min": partnumber})])
    mounts = {"filesystems": [{"source": f"/dev/{partname}", "target": "/run/media/deck/card", "fstype": "ext4", "options": "rw,nosuid", "maj:min": partnumber}]}
    return discover({"blockdevices": [disk]}, mounts, facts)[0]


def inventory(device):
    return ([deepcopy(device)], [], [])


def clean_journal(records=None):
    return {"status": "ok", "message": "ok", "records": records or [], "limited": False}


class PolicyTests(unittest.TestCase):
    def test_sd_and_usb_data_partitions_are_eligible(self):
        for usb in (False, True):
            device = managed_device(usb)
            self.assertEqual(eligibility(device, device["partitions"][1]), "")

    def test_whole_disk_unmounted_multimount_swap_efi_and_missing_identity_rejected(self):
        device = managed_device()
        self.assertTrue(eligibility(device, device["partitions"][0]))
        changes = [{"mounts": []}, {"mounts": device["partitions"][1]["mounts"] * 2},
                   {"filesystem": "swap"}, {"filesystem": "vfat"}, {"partitionType": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"},
                   {"uuid": None}, {"partitionUuid": None}, {"majorMinor": "8:9"}]
        for change in changes:
            with self.subTest(change=change):
                part = {**deepcopy(device["partitions"][1]), **change}
                self.assertTrue(eligibility(device, part))

    def test_system_topology_emmc_holders_and_mapping_rejected(self):
        for change in [{"topology": "/sys/devices/pci/nvme/nvme0/nvme0n1"},
                       {"sysfs": {"card_type": "MMC"}}, {"managementBlocked": True},
                       {"sysfs": {"holders": ["dm-0"]}}]:
            device = {**managed_device(), **change}
            self.assertTrue(eligibility(device, device["partitions"][1]))

    def test_any_system_or_non_data_mount_on_parent_disk_blocks_operation(self):
        for target in ("/", "/home", "/boot/efi", "/var/lib", "/etc", "/run/media/../home", "/mnt//bad"):
            device = managed_device()
            device["partitions"][0]["mounts"] = [{"target": target, "readOnly": False}]
            self.assertTrue(eligibility(device, device["partitions"][1]), target)

    def test_fault_evidence_scoped_to_target_partition_and_current_boot(self):
        part = managed_device()["partitions"][1]
        rows = [record("EXT4-fs (mmcblk0p1): emergency_ro", 1),
                record("Aborting journal on device mmcblk0p1-8", 2),
                record("EXT4-fs (mmcblk0p1): filesystem check required", 3)]
        self.assertEqual(len(filesystem_warnings(rows, part, "current")), 3)
        self.assertEqual(filesystem_warnings([record("EXT4-fs (mmcblk0p2): journal aborted")], part, "current"), [])
        self.assertEqual(filesystem_warnings([record("EXT4-fs (mmcblk0p1): emergency_ro", boot="previous")], part, "current"), [])
        self.assertEqual(filesystem_warnings([record("EXT4-fs (mmcblk0p1): mounted filesystem errors=remount-ro")], part, "current"), [])

    def test_live_block_node_sysfs_and_swap_file_checks(self):
        device = managed_device()
        part = device["partitions"][1]
        def facts(name):
            return deepcopy(device["sysfs"] if name == device["name"] else part["sysfs"])
        with patch("storage_guard.remount.sysfs_facts", facts), patch("storage_guard.remount.os.stat", return_value=SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(179, 1))), patch(
            "storage_guard.remount.Path.read_text", return_value="Filename Type Size Used Priority\n"):
            live_check(device, part)
            with patch("storage_guard.remount.os.stat", return_value=SimpleNamespace(st_mode=stat.S_IFREG, st_rdev=0)), self.assertRaises(ReadFailure):
                live_check(device, part)
            with patch("storage_guard.remount.Path.read_text", return_value="Filename Type Size Used Priority\n/run/media/deck/card/swapfile file 1 1 1\n"), self.assertRaises(ReadFailure) as caught:
                live_check(device, part)
            self.assertEqual(caught.exception.status, "device_busy")

    def test_live_diskseq_change_is_rejected_before_command(self):
        device = managed_device()
        facts = {**device["sysfs"], "diskseq": "43"}
        with patch("storage_guard.remount.sysfs_facts", return_value=facts), self.assertRaises(ReadFailure):
            live_check(device, device["partitions"][1])

    def test_other_partition_with_mapping_blocks_parent(self):
        device = managed_device()
        sibling = deepcopy(device["partitions"][1])
        sibling["name"] = "mmcblk0p2"
        sibling["path"] = "/dev/mmcblk0p2"
        sibling["sysfs"]["holders"] = ["dm-0"]
        device["partitions"].append(sibling)
        self.assertTrue(eligibility(device, device["partitions"][1]))

    def test_exfat_and_ntfs_preserve_numeric_access_permissions_and_safe_flags(self):
        for filesystem in ("exfat", "ntfs", "ntfs3"):
            device = managed_device(True)
            part = device["partitions"][1]
            part["filesystem"] = filesystem
            part["mounts"][0]["options"] = "rw,nosuid,nodev,uid=1000,gid=1000,fmask=0022,dmask=0022,untrusted-option"
            self.assertEqual(eligibility(device, part), "")
            self.assertEqual(mount_options(part, True), ["ro", "nosuid", "nodev", "uid=1000", "gid=1000", "fmask=0022", "dmask=0022"])
            part["mounts"][0]["options"] = "rw,uid=1000,gid=1000,uid=2000"
            self.assertTrue(eligibility(device, part))
            part["mounts"][0]["options"] = "rw,nosuid"
            self.assertTrue(eligibility(device, part))

    def test_partition_hosting_plugin_runtime_is_not_a_management_target(self):
        device = managed_device()
        with patch.dict(os.environ, {"DECKY_PLUGIN_RUNTIME_DIR": "/run/media/deck/card/homebrew/data/plugin"}):
            self.assertIn("Decky", eligibility(device, device["partitions"][1]))


class TransactionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.device = managed_device()
        self.unmounted = deepcopy(self.device)
        self.unmounted["partitions"][1]["mounts"] = []
        self.manager = Remounter()
        self.manager.decorate([self.device], [], "current", True)
        self.token = self.device["partitions"][1]["management"]["token"]

    async def execute(self, scans=None, outputs=None, rows=None, progress=None):
        scans = scans if scans is not None else [self.device, self.device, self.unmounted, self.device]
        with patch("storage_guard.remount.scan", AsyncMock(side_effect=[inventory(d) if d else ([], [], []) for d in scans])), patch(
            "storage_guard.remount.live_check"), patch("storage_guard.remount.read_journal", AsyncMock(return_value=clean_journal(rows))), patch(
            "storage_guard.remount.run", AsyncMock(side_effect=outputs or [Output(0, "ok", ""), Output(0, "ok", "")])) as command:
            result = await self.manager.execute(self.token, "current", progress)
        return result, command

    async def test_ordered_success_only_fixed_noninteractive_udisks_commands(self):
        result, command = await self.execute()
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["unmounted"] and result["mounted"])
        self.assertEqual([call.args[0] for call in command.call_args_list], [
            ["udisksctl", "unmount", "-b", "/dev/mmcblk0p1", "--no-user-interaction"],
            ["udisksctl", "mount", "-b", "/dev/mmcblk0p1", "--no-user-interaction", "--options", "nosuid"]])

    async def test_arbitrary_path_expired_and_replayed_tokens_never_execute(self):
        with patch("storage_guard.remount.run", AsyncMock()) as command:
            for value in ("/dev/nvme0n1p1", "../../etc/passwd", {"path": "/dev/sda1"}, None):
                self.assertEqual((await self.manager.execute(value, "current"))["status"], "invalid_target")
            self.manager.grants[self.token].expires = 0
            self.assertEqual((await self.manager.execute(self.token, "current"))["status"], "invalid_target")
            command.assert_not_called()

    async def test_same_token_or_other_token_from_old_snapshot_not_reusable(self):
        self.manager.decorate([self.device], [], "current", True)
        other = self.device["partitions"][1]["management"]["token"]
        await self.execute()
        with patch("storage_guard.remount.run", AsyncMock()) as command:
            for token in (self.token, other):
                self.assertEqual((await self.manager.execute(token, "current"))["status"], "invalid_target")
            command.assert_not_called()

    async def test_wrong_uuid_diskseq_mount_and_new_system_mount_stop_before_unmount(self):
        for field, value in (("uuid", "different-card"), ("majorMinor", "179:2"), ("partitionUuid", "other")):
            self.setUp()
            changed = deepcopy(self.device)
            changed["partitions"][1][field] = value
            result, command = await self.execute(scans=[changed])
            self.assertEqual(result["status"], "stale_target")
            command.assert_not_called()
        for mode in ("diskseq", "mount", "system"):
            self.setUp()
            changed = deepcopy(self.device)
            if mode == "diskseq":
                changed["sysfs"]["diskseq"] = "43"
            else:
                changed["partitions"][1]["mounts"][0]["target"] = "/" if mode == "system" else "/run/media/deck/other"
            result, command = await self.execute(scans=[changed])
            self.assertEqual(result["status"], "stale_target")
            command.assert_not_called()

    async def test_disconnect_before_validation_and_after_unmount(self):
        result, command = await self.execute(scans=[None])
        self.assertEqual(result["status"], "device_disconnected")
        command.assert_not_called()
        self.setUp()
        result, command = await self.execute(scans=[self.device, self.device, None])
        self.assertIsNone(result["unmounted"])  # Exit 0, but no observation of absence after disconnect.
        self.assertEqual(command.call_count, 1)

    async def test_busy_permission_unmount_failure_stop_without_mount(self):
        for detail, status in (("Device busy", "device_busy"), ("Not authorized to perform operation", "permission_denied"), ("unmount failed", "unmount_failed")):
            self.setUp()
            result, command = await self.execute(outputs=[Output(1, "", detail)])
            self.assertEqual(result["status"], status)
            self.assertFalse(result["unmounted"])
            self.assertEqual(command.call_count, 1)

    async def test_mount_failure_preserves_unmounted_result_and_reason(self):
        result, command = await self.execute(outputs=[Output(0, "", ""), Output(1, "", "wrong fs type, bad superblock")])
        self.assertEqual(result["status"], "mount_failed")
        self.assertTrue(result["unmounted"])
        self.assertIn("bad superblock", result["detail"])
        self.assertEqual(result["phase"], "mount")
        self.assertEqual(command.call_count, 2)

    async def test_replacement_or_automount_after_unmount_never_mounts(self):
        for automount in (False, True):
            self.setUp()
            changed = deepcopy(self.unmounted)
            if automount:
                changed = deepcopy(self.device)
            else:
                changed["sysfs"]["diskseq"] = "43"
            result, command = await self.execute(scans=[self.device, self.device, changed])
            self.assertEqual(result["status"], "stale_target")
            self.assertEqual(command.call_count, 1)

    async def test_post_mount_missing_mount_is_not_success(self):
        result, command = await self.execute(scans=[self.device, self.device, self.unmounted, self.unmounted])
        self.assertEqual(result["status"], "verification_failed")
        self.assertEqual(command.call_count, 2)

    async def test_current_readonly_is_preserved_but_historical_journal_never_forces_ro(self):
        self.device["partitions"][1]["mounts"][0]["readOnly"] = True
        self.manager.decorate([self.device], [], "current", True)
        self.token = self.device["partitions"][1]["management"]["token"]
        result, command = await self.execute()
        self.assertEqual(result["status"], "success")
        self.assertIn("ro", command.call_args.args[0][-1].split(","))
        self.setUp()
        result, command = await self.execute(rows=[record("EXT4-fs (mmcblk0p1): journal aborted")])
        self.assertEqual(result["status"], "success")
        self.assertNotIn("ro", command.call_args.args[0][-1].split(","))
        self.assertNotIn("rw", command.call_args.args[0][-1].split(","))
        self.assertTrue(result["warnings"])

    async def test_live_emergency_ro_remains_protected(self):
        self.device["partitions"][1]["mounts"][0]["options"] += ",emergency_ro"
        self.manager.decorate([self.device], [], "current", True)
        self.token = self.device["partitions"][1]["management"]["token"]
        final = deepcopy(self.device)
        final["partitions"][1]["mounts"][0]["readOnly"] = True
        result, command = await self.execute(scans=[self.device, self.device, self.unmounted, final])
        self.assertEqual(result["status"], "success")
        self.assertIn("ro", command.call_args.args[0][-1].split(","))

    async def test_repair_followed_by_normal_mount_does_not_inherit_old_readonly_decision(self):
        rows = [record("EXT4-fs (mmcblk0p1): journal aborted", 1),
                record("EXT4-fs (mmcblk0p1): mounted filesystem with ordered data mode. r/w", 2)]
        warnings = filesystem_warnings(rows, self.device["partitions"][1], "current")
        self.assertIn("历史记录", warnings[0])
        self.assertIn("是否修复未确认", warnings[0])
        result, command = await self.execute(rows=rows)
        self.assertEqual(result["status"], "success")
        self.assertNotIn("ro", command.call_args.args[0][-1].split(","))

    async def test_timeout_does_not_continue_unknown_unmount(self):
        result, command = await self.execute(outputs=[ReadFailure("timeout", "超时")])
        self.assertEqual(result["status"], "timeout")
        self.assertIsNone(result["unmounted"])
        self.assertEqual(command.call_count, 1)

    async def test_missing_udisks_and_failed_journal_access(self):
        with patch("storage_guard.remount.read_journal", AsyncMock(side_effect=ReadFailure("permission_denied", "无权限"))), patch(
            "storage_guard.remount.scan", AsyncMock(return_value=inventory(self.device))), patch("storage_guard.remount.live_check"), patch(
            "storage_guard.remount.run", AsyncMock(side_effect=ReadFailure("missing_command", "udisksctl 未安装"))):
            result = await self.manager.execute(self.token, "current")
        self.assertEqual(result["status"], "missing_command")
        self.assertTrue(result["warnings"])

    async def test_new_identity_after_safety_log_read_is_rejected(self):
        replacement = deepcopy(self.device)
        replacement["sysfs"]["diskseq"] = "100"
        result, command = await self.execute(scans=[self.device, replacement])
        self.assertEqual(result["status"], "stale_target")
        command.assert_not_called()

    async def test_requested_current_readonly_not_verified_is_not_success(self):
        writable = deepcopy(self.device)
        self.device["partitions"][1]["mounts"][0]["readOnly"] = True
        self.manager.decorate([self.device], [], "current", True)
        self.token = self.device["partitions"][1]["management"]["token"]
        result, command = await self.execute(scans=[self.device, self.device, self.unmounted, writable])
        self.assertIn("ro", command.call_args.args[0][-1].split(","))
        self.assertEqual(result["status"], "verification_failed")



class ServiceManagementTests(unittest.IsolatedAsyncioTestCase):
    async def test_operation_failure_always_refreshes_and_is_retained(self):
        service = Service()
        with patch.object(service.remounter, "execute", AsyncMock(return_value={"status": "mount_failed", "warnings": []})), patch(
            "storage_guard.service.scan", AsyncMock(return_value=inventory(managed_device()))) as scanner, patch(
            "storage_guard.service.read_journal", AsyncMock(return_value=clean_journal())) as reader:
            result = await service.remount("token")
            self.assertEqual(result["snapshot"]["lastOperation"]["status"], "mount_failed")
            self.assertEqual(service.last_operation["status"], "mount_failed")
            scanner.assert_awaited_once()
            reader.assert_awaited_once_with("boot")
        await service.close()

    async def test_overlapping_requests_rejected_and_request_cancellation_does_not_cancel_mount(self):
        service = Service()
        started, finish = asyncio.Event(), asyncio.Event()
        async def slow(*args):
            started.set()
            await finish.wait()
            return {"status": "success", "warnings": []}
        with patch.object(service.remounter, "execute", slow), patch.object(service, "_snapshot", AsyncMock(return_value={})):
            first = asyncio.create_task(service.remount("token"))
            await started.wait()
            self.assertEqual((await service.remount("token"))["operation"]["status"], "busy")
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            self.assertTrue(service.managing)
            closer = asyncio.create_task(service.close())
            await asyncio.sleep(0)
            self.assertFalse(closer.done())
            finish.set()
            await closer
            self.assertEqual(service.last_operation["status"], "success")
