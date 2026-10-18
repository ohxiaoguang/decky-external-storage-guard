import unittest
from storage_guard.devices import discover, sysfs_facts
from pathlib import Path
from tempfile import TemporaryDirectory
from helpers import node, sd_device, usb_device


class DiscoveryTests(unittest.TestCase):
    def test_native_sd_without_usb_transport(self):
        device = sd_device()
        self.assertEqual(device["kind"], "SD")
        self.assertEqual(device["controller"], "mmc0")
        self.assertEqual(len(device["partitions"]), 2)
        self.assertFalse(device["mounted"])

    def test_names_and_removable_flag_do_not_make_external(self):
        for name in ("sda", "mmcblk0", "nvme0n1"):
            self.assertEqual(discover({"blockdevices": [node(name, rm=True)]}, {}, {}), [])

    def test_internal_emmc_excluded(self):
        self.assertEqual(discover({"blockdevices": [node("mmcblk0")]}, {}, {
            "mmcblk0": {"topology": "/sys/mmc_host/mmc0/mmc0:0001/block/mmcblk0", "card_type": "MMC"}
        }), [])

    def test_usb_topology_even_without_tran(self):
        result = discover({"blockdevices": [node("sdb")]}, {}, {
            "sdb": {"topology": "/sys/pci/usb2/2-1/2-1.3/2-1.3:1.0/block/sdb"}})
        self.assertEqual(result[0]["usbPort"], "2-1.3")

    def test_unknown_rotation_is_unknown_kind(self):
        result = discover({"blockdevices": [node("sdc", tran="usb", rota=None)]}, {}, {})
        self.assertEqual(result[0]["kind"], "Unknown")

    def test_hdd_and_ssd(self):
        devices = discover({"blockdevices": [node("sda", tran="usb", rota=1), node("sdb", tran="usb", rota=0)]}, {}, {})
        self.assertEqual([d["kind"] for d in devices], ["USB HDD", "USB SSD"])

    def test_internal_nvme_excluded_external_usb_nvme_allowed(self):
        devices = discover({"blockdevices": [node("nvme0n1", tran="nvme"), node("nvme1n1", tran="nvme")]}, {}, {
            "nvme0n1": {"topology": "/sys/devices/pci/nvme/nvme0/nvme0n1"},
            "nvme1n1": {"topology": "/sys/devices/pci/usb4/4-1/4-1:1.0/nvme/nvme1n1"}})
        self.assertEqual([d["name"] for d in devices], ["nvme1n1"])

    def test_system_disk_excluded_even_usb_with_mapped_root(self):
        disk = node("sda", tran="usb", children=[node("sda2", type="part", children=[
            node("dm-0", type="crypt", **{"maj:min": "253:0"})])])
        mounts = {"filesystems": [{"source": "/dev/mapper/root", "target": "/", "maj:min": "253:0"}]}
        self.assertEqual(discover({"blockdevices": [disk]}, mounts, {}), [])

    def test_findmnt_reports_real_ro_and_multiple_mounts(self):
        disk = node("sda", tran="usb", children=[node("sda1", type="part", fstype="exfat", **{"maj:min": "8:1"})])
        mounts = {"filesystems": [
            {"source": "/dev/sda1", "target": "/run/media/card", "options": "ro,nosuid", "fstype": "exfat", "maj:min": "8:1"},
            {"source": "/dev/sda1", "target": "/mnt/card", "options": "rw,errors=remount-ro", "maj:min": "8:1"}]}
        device = discover({"blockdevices": [disk]}, mounts, {})[0]
        self.assertTrue(device["readOnly"])
        self.assertTrue(device["mounted"])
        self.assertEqual(len(device["partitions"][1]["mounts"]), 2)
        self.assertFalse(device["partitions"][1]["mounts"][1]["readOnly"])

    def test_multiple_devices_and_missing_sysfs(self):
        self.assertEqual(sysfs_facts("gone", Path("/not/a/sysfs"))["topology"], "")
        devices = discover({"blockdevices": [node("sda", tran="usb"), node("sdb", tran="usb")]}, {}, {})
        self.assertEqual(len(devices), 2)

    def test_real_sysfs_symlink_read(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "devices/mmc_host/mmc0/mmc0:aaaa/block/mmcblk0"
            (target / "device").mkdir(parents=True)
            (target / "device/type").write_text("SD\n")
            (root / "class").mkdir()
            (root / "class/mmcblk0").symlink_to(target)
            self.assertEqual(sysfs_facts("mmcblk0", root / "class")["card_type"], "SD")
