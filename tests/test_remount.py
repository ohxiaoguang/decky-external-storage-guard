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
from storage_guard.remount import PartitionManager, eligibility, live_check, mount_options
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
