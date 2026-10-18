import unittest
from storage_guard.events import analyze
from storage_guard.rules import classify
from helpers import sd_device, usb_device, record


class EventTests(unittest.TestCase):
    def parse(self, messages, devices=None, boot="current", excluded=None):
        rows = [record(msg, i + 1, boot) for i, msg in enumerate(messages)]
        return analyze(rows, devices if devices is not None else [sd_device(), usb_device()], excluded or ["nvme0n1", "nvme0n1p1"], "current")[0]

    def test_real_ally_logs(self):
        messages = [
            "mmc0: error -84 reading general info of SD ext reg",
            "mmc0: error -84 whilst initialising SD card",
            "mmc0: new UHS-I speed SDR104 SDXC card at address aaaa",
            "mmcblk0: mmc0:aaaa SN512 477 GiB",
            "EXT4-fs (mmcblk0p1): mounted filesystem ... r/w with ordered data mode",
            "mmc0: Tuning failed, falling back to fixed sampling clock",
            "mmc0: error -84 writing Cache Flush bit",
            "I/O error, dev mmcblk0, sector 0 op 0x1:(WRITE) flags 0x800 phys_seg 0 prio class 2",
            "darkest.bin.x86: segfault at 44",
        ]
        events = self.parse(messages)
        self.assertEqual(len(events), 8)
        kinds = {e["kind"]: e for e in events}
        self.assertEqual(kinds["tuning"]["severity"], "Warning")
        self.assertEqual(kinds["cache_flush"]["severity"], "Error")
        self.assertEqual(kinds["io_error"]["deviceId"], "/dev/mmcblk0")
        self.assertEqual(kinds["mount"]["severity"], "Info")
        self.assertIsNone(kinds["initialization"]["deviceId"])
        self.assertEqual(events[0]["timestamp"], 8000)

    def test_repeated_tuning_is_counted_not_damage_diagnosis(self):
        events = self.parse(["mmc0: Tuning failed"] * 8)
        self.assertEqual(len(events), 8)
        self.assertTrue(all(e["severity"] == "Warning" for e in events))

    def test_usb_io_and_partition_association(self):
        self.assertEqual(self.parse(["I/O error, dev sda, sector 1"])[0]["deviceId"], "/dev/sda")
        self.assertEqual(self.parse(["EXT4-fs (mmcblk0p1): error: corruption"])[0]["deviceId"], "/dev/mmcblk0")

    def test_mouse_usb_events_ignored_storage_ports_correlated(self):
        events = self.parse(["usb 2-2: USB disconnect, device number 7", "usb 2-2: reset SuperSpeed USB device",
                             "usb 2-1: reset SuperSpeed USB device number 2 using xhci_hcd"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["deviceId"], "/dev/sda")

    def test_usb_disconnect_and_scsi_uas(self):
        events = self.parse(["sd 6:0:0:0: [sda] tag#1 FAILED Result: hostbyte=DID_ERROR", "usb 2-1: USB disconnect, device number 2"])
        self.assertEqual(events[0]["kind"], "disconnect")
        self.assertEqual(events[0]["severity"], "Info")
        self.assertEqual(events[0]["deviceId"], "/dev/sda")
        self.assertIsNone(events[1]["deviceId"])  # older generation is uncertain
        uas = self.parse(["sd 6:0:0:0: uas_eh_abort_handler 0 uas-tag 1 inflight: CMD"])
        self.assertEqual(uas[0]["severity"], "Warning")
        self.assertEqual(uas[0]["deviceId"], "/dev/sda")

    def test_internal_disk_errors_excluded(self):
        self.assertEqual(self.parse(["I/O error, dev nvme0n1", "EXT4-fs (nvme0n1p1): error corruption"]), [])
        self.assertEqual(self.parse(["I/O error, dev sdb"], excluded=["sdb"]), [])

    def test_missing_devices_keep_storage_errors_unassociated(self):
        events = self.parse(["I/O error, dev mmcblk0", "mmc0: error -84 whilst initialising SD card"], devices=[])
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e["deviceId"] is None for e in events))

    def test_prior_boot_never_uses_current_device_names_or_ports(self):
        events = self.parse(["I/O error, dev sda", "mmc0: Tuning failed", "usb 2-1: USB disconnect, device number 2"], boot="previous")
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e["deviceId"] is None for e in events))

    def test_ambiguous_controller_never_guessed(self):
        sd1, sd2 = sd_device(), sd_device()
        sd2["id"] = "/dev/mmcblk1"
        events = self.parse(["mmc0: Tuning failed"], devices=[sd1, sd2])
        self.assertIsNone(events[0]["deviceId"])

    def test_name_boundary_avoids_sda_matching_sdaa(self):
        event = self.parse(["I/O error, dev sdaa"])[0]
        self.assertIsNone(event["deviceId"])

    def test_mount_options_and_game_crash_not_errors(self):
        self.assertIsNone(classify("darkest.bin.x86: segfault at 44"))
        self.assertIsNone(classify("EXT4-fs (mmcblk0p1): mounted with options errors=remount-ro"))
        self.assertEqual(self.parse(["EXT4-fs (mmcblk0p1): mounted filesystem rw, errors=remount-ro"])[0]["severity"], "Info")

    def test_readonly_requires_observed_transition(self):
        self.assertEqual(self.parse(["EXT4-fs (mmcblk0p1): Remounting filesystem read-only"])[0]["severity"], "Error")
        self.assertIsNone(classify("mmcblk0: Write Protect is on"))

    def test_exfat_ntfs_crc_timeout(self):
        for msg, kind, severity in [
            ("exfat-fs (sda): error, invalid boot record", "filesystem", "Error"),
            ("ntfs3: sda: volume is corrupt", "filesystem", "Error"),
            ("mmc0: CRC error", "crc", "Warning"),
            ("sd 6:0:0:0: command timed out", "timeout", "Warning"),
            ("usb 2-1: device descriptor read/64, error -110", "initialization", "Error"),
        ]:
            with self.subTest(msg=msg):
                event = self.parse([msg])[0]
                self.assertEqual((event["kind"], event["severity"]), (kind, severity))

    def test_bounded_newest_events(self):
        records = [record("mmc0: Tuning failed", i + 1) for i in range(700)]
        events, limited = analyze(records, [sd_device()], [], "current")
        self.assertTrue(limited)
        self.assertEqual(len(events), 500)
        self.assertEqual(events[0]["timestamp"], 700000)

    def test_same_boot_replacement_does_not_inherit_earlier_errors(self):
        events = self.parse(["I/O error, dev sda", "sd 6:0:0:0: [sda] Attached SCSI disk", "I/O error, dev sda"])
        self.assertEqual(events[0]["deviceId"], "/dev/sda")
        self.assertIsNone(events[-1]["deviceId"])

    def test_disconnected_usb_with_explicit_historical_storage_evidence(self):
        events = self.parse(["usb-storage 2-3:1.0: USB Mass Storage device detected",
                             "usb 2-3: reset high-speed USB device number 4 using xhci_hcd",
                             "usb 2-3: USB disconnect, device number 4",
                             "usb 2-3: USB disconnect, device number 5"], devices=[])
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e["deviceId"] is None for e in events))

    def test_internal_emmc_controller_errors_not_external(self):
        self.assertEqual(self.parse(["mmc1: Tuning failed"], excluded=["mmc1"]), [])

    def test_confirmed_offline_io_is_error_plain_removal_is_information(self):
        event = self.parse(["sd 6:0:0:0: rejecting I/O to offline device"])[0]
        self.assertEqual((event["kind"], event["severity"]), ("offline", "Error"))

    def test_usb_mouse_history_on_reused_port_is_not_storage(self):
        events = self.parse(["usb 2-1: reset high-speed USB device number 2 using xhci_hcd",
                             "usb 2-1: USB disconnect, device number 2",
                             "sd 6:0:0:0: [sda] Attached SCSI disk"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "recognized")
