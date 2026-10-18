import asyncio
from copy import deepcopy
import errno
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from helpers import sd_device, usb_device
from test_suspend import log, cycle_rows
from storage_guard.commands import ReadFailure, Output
from storage_guard.events import analyze
from storage_guard.export import export_text, desktop_user
from storage_guard.hardware import reader_info, enrich_readers
from storage_guard.report import build_report, Redactor, MAX_REPORT_BYTES
from storage_guard.service import Service
from storage_guard.suspend import pair_cycles, annotate


def report_fixture():
    devices = [sd_device(), usb_device()]
    part = devices[0]["partitions"][1]
    part["uuid"], part["partitionUuid"] = "77777777-abcd-abcd-abcd-777777777777", "11111111-2222-3333-4444-555555555555"
    part["mounts"] = [{"target": "/run/media/alice/MyPrivateCard", "filesystem": "ext4", "readOnly": False}]
    devices[0]["reader"] = {"controller": "mmc0", "pciAddress": "0000:03:00.0", "pciId": "10ec:525a", "driver": "sdhci-pci", "model": None}
    rows = cycle_rows() + [log("mmc0: controller diagnostic register 0xABCD", 16, 4606),
        log("I/O error, dev mmcblk0, sector 99", 52, 4642),
        log("EXT4-fs (mmcblk0p1): error on /run/media/alice/MyPrivateCard token=top secret value", 53, 4643),
        log("usb 2-1: SerialNumber: private-serial-number", 54, 4644),
        log("usb 2-2: mouse USB disconnect", 55, 4645),
        log("I/O error, dev nvme0n1", 56, 4646),
        log("darkest.bin.x86: segfault at 44", 57, 4647),
        log("network: password=unrelated-secret", 58, 4648)]
    events, _ = analyze(rows, devices, ["nvme0n1"], "boot-a")
    cycles = pair_cycles(rows)
    annotate(events, cycles)
    contexts, _ = analyze(rows, devices, ["nvme0n1"], "boot-a", include_context=True, max_events=12000)
    snapshot = {"devices": devices, "events": events, "warnings": [], "window": "boot",
        "deviceStatus": {"status": "ok", "message": "ok"}, "journalStatus": {"status": "ok", "message": "ok", "limited": False}}
    capture = {"records": rows, "cycles": cycles, "contextRecords": [e["record"] for e in contexts]}
    return snapshot, capture


HARDWARE = {"os": "SteamOS test fixture", "kernel": "6.11.0-test", "model": "ROG Ally X fixture"}


class ReportTests(unittest.TestCase):
    def test_summary_raw_unclassified_context_and_structured_timestamps_present(self):
        snapshot, capture = report_fixture()
        report = build_report(snapshot, capture, HARDWARE, 1000000)
        text = report["text"]
        for expected in ("简短摘要", "完整原始诊断消息", "controller diagnostic register 0xABCD", '"__MONOTONIC_TIMESTAMP"',
                         '"_BOOT_ID":"boot-a"', "10ec:525a", "sdhci-pci", "6.11.0-test"):
            self.assertIn(expected, text)
        self.assertIn("唤醒后约38.000秒", text)
        self.assertIn("PM: suspend entry", text)
        self.assertNotIn("controller diagnostic register", report["summary"])

    def test_unrelated_game_mouse_internal_ssd_and_metadata_secrets_excluded(self):
        snapshot, capture = report_fixture()
        for row in capture["contextRecords"]:
            row["_CMDLINE"] = "--password=metadata-secret"
            row["_HOSTNAME"] = "private-hostname"
        text = build_report(snapshot, capture, HARDWARE)["text"]
        for hidden in ("darkest.bin", "mouse", "nvme0n1", "unrelated-secret", "metadata-secret", "private-hostname", "_CMDLINE"):
            self.assertNotIn(hidden, text)

    def test_default_redaction_retains_device_and_pci_ids_but_hides_private_values(self):
        snapshot, capture = report_fixture()
        with patch.dict(os.environ, {"DECKY_USER": "alice"}):
            text = build_report(snapshot, capture, HARDWARE)["text"]
        for hidden in ("MyPrivateCard", "/run/media/alice", "top secret value", "private-serial-number", "77777777-abcd", "11111111-2222"):
            self.assertNotIn(hidden, text)
        self.assertIn("/dev/mmcblk0p1", text)
        self.assertIn("10ec:525a", text)
        self.assertIn("已隐藏", text)

    def test_common_credentials_urls_paths_and_hex_ids_are_redacted_consistently(self):
        redactor = Redactor([])
        for value in ('password="two word secret"', "access_token=very-private-token", "Authorization: Bearer abcdef.12345", "https://user:password@private.example/path?token=secret", "cid=aaaabbbbccccdddd", "SerialNumber: name with spaces"):
            result = redactor.text(value)
            for secret in ("two word secret", "very-private-token", "abcdef.12345", "private.example", "aaaabbbbccccdddd", "name with spaces"):
                self.assertNotIn(secret, result)
        self.assertEqual(redactor.text("/home/alice/private"), redactor.text("/home/alice/private"))
        self.assertNotEqual(Redactor([]).text("/home/alice/private"), redactor.text("/home/alice/private"))
        self.assertNotIn("unique-unlabelled-serial", Redactor([], ["unique-unlabelled-serial"]).text("mmc0: unique-unlabelled-serial"))

    def test_size_cap_retains_latest_raw_subset_and_marks_truncation(self):
        snapshot, capture = report_fixture()
        capture["contextRecords"] = [log(f"mmc0: trace {i} " + "x" * 4000, i + 1, i + 1) for i in range(700)]
        capture["records"] = capture["contextRecords"]
        report = build_report(snapshot, capture, HARDWARE)
        self.assertTrue(report["truncated"])
        self.assertLessEqual(report["size"], MAX_REPORT_BYTES)
        self.assertLess(report["rawCount"], 700)
        self.assertIn("trace 699", report["text"])

    def test_no_permissions_or_history_does_not_make_healthy_report(self):
        snapshot, capture = report_fixture()
        snapshot["events"], capture["records"], capture["contextRecords"], capture["cycles"] = [], [], [], []
        for status in ("permission_denied", "no_history", "no_logs", "timeout"):
            snapshot["journalStatus"] = {"status": status, "message": "读取不可用"}
            text = build_report(snapshot, capture, {**HARDWARE, "model": None})["text"]
            self.assertIn(status, text)
            self.assertIn("无法可靠识别", text)
            self.assertIn("未发现可配对", text)
            self.assertNotIn("设备正常", text)

    def test_historical_range_does_not_claim_complete_history_from_current_boot(self):
        snapshot, capture = report_fixture()
        for window in ("day", "week", "all"):
            snapshot["window"] = window
            report = build_report(snapshot, capture, HARDWARE)
            self.assertIn("读取到 1 个启动周期", report["text"])
            self.assertIn("不能保证覆盖整个所选时段", report["summary"])

    def test_actual_boot_id_not_replaced_by_redaction_of_message_identifiers(self):
        snapshot, capture = report_fixture()
        boot = "1234567890abcdef1234567890abcdef"
        for row in capture["records"]:
            row["_BOOT_ID"] = boot
        for event in snapshot["events"]:
            event["bootId"] = boot
        text = build_report(snapshot, capture, HARDWARE)["text"]
        self.assertIn('"_BOOT_ID":"' + boot + '"', text)
        self.assertIn("Boot=" + boot, text)


class ExportTests(unittest.TestCase):
    def test_utf8_file_user_ownership_permissions_and_no_arbitrary_name(self):
        with TemporaryDirectory() as directory:
            identity = (Path(directory), os.getuid(), os.getgid())
            result = export_text("中文诊断\nI/O error\n", identity)
            path = Path(result["path"])
            self.assertEqual(path.parent, Path(directory) / "Downloads/External-Storage-Guard")
            self.assertEqual(path.read_text(encoding="utf-8"), "中文诊断\nI/O error\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.stat().st_uid, os.getuid())
            self.assertEqual(result["encoding"], "UTF-8")

    def test_symlink_download_or_plugin_folder_is_refused(self):
        for child in ("Downloads", "External-Storage-Guard"):
            with self.subTest(child=child), TemporaryDirectory() as home, TemporaryDirectory() as target:
                base = Path(home)
                if child != "Downloads":
                    base = base / "Downloads"
                    base.mkdir()
                (base / child).symlink_to(target, target_is_directory=True)
                with self.assertRaises(ReadFailure):
                    export_text("report", (Path(home), os.getuid(), os.getgid()))
                self.assertEqual(list(Path(target).iterdir()), [])

    def test_existing_files_never_overwritten(self):
        with TemporaryDirectory() as home:
            (Path(home) / "Downloads").write_text("important")
            with self.assertRaises(ReadFailure):
                export_text("report", (Path(home), os.getuid(), os.getgid()))
            self.assertEqual((Path(home) / "Downloads").read_text(), "important")

    def test_write_failure_removes_partial_report(self):
        with TemporaryDirectory() as home, patch("storage_guard.export.os.fsync", side_effect=OSError(errno.ENOSPC, "disk full")):
            with self.assertRaises(ReadFailure) as caught:
                export_text("report", (Path(home), os.getuid(), os.getgid()))
            self.assertEqual(caught.exception.status, "export_failed")
            self.assertEqual(list((Path(home) / "Downloads/External-Storage-Guard").iterdir()), [])

    def test_filename_collision_cannot_delete_or_overwrite_existing_report(self):
        with TemporaryDirectory() as home, patch("storage_guard.export.secrets.token_hex", return_value="fixed"), patch("storage_guard.export.datetime") as clock:
            clock.now.return_value.strftime.return_value = "fixed-time-"
            identity = (Path(home), os.getuid(), os.getgid())
            first = export_text("keep this report", identity)
            with self.assertRaises(ReadFailure):
                export_text("new report", identity)
            self.assertEqual(Path(first["path"]).read_text(), "keep this report")

    def test_no_decky_user_root_or_mismatched_home_never_falls_back_to_root(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ReadFailure):
            desktop_user()
        with patch.dict(os.environ, {"DECKY_USER": "root"}), patch("storage_guard.export.pwd.getpwnam", return_value=SimpleNamespace(pw_uid=0, pw_gid=0, pw_dir="/root")), self.assertRaises(ReadFailure):
            desktop_user()


class ReportServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_is_readonly_and_exports_only_cached_sanitized_text(self):
        service = Service()
        snapshot, capture = report_fixture()
        async def collect(window, capture=None, management=True):
            self.assertFalse(management)
            capture.update(report_fixture()[1])
            return snapshot
        with patch.object(service, "_snapshot", collect), patch("storage_guard.service.system_info", return_value=HARDWARE), patch(
            "storage_guard.service.enrich_readers", AsyncMock()), patch.object(service.remounter, "execute", AsyncMock()) as mutate:
            report = await service.generate_report("boot")
            self.assertEqual(report["status"], "ok")
            self.assertNotIn("top secret value", report["text"])
            with patch("storage_guard.service.export_text", return_value={"path": "/test/report.txt"}) as exporter:
                result = await service.export_report(report["reportId"])
                self.assertEqual(result["status"], "ok")
                exporter.assert_called_once_with(report["text"])
            mutate.assert_not_called()
        await service.close()
        self.assertEqual(service.reports, {})

    async def test_unknown_expired_report_id_and_invalid_range_rejected(self):
        service = Service()
        with patch("storage_guard.service.export_text") as exporter:
            for key in ("/etc/passwd", "../../file", None, {"path": "/tmp/file"}):
                with self.assertRaises(ReadFailure):
                    await service.export_report(key)
            service.reports["old"] = {"expires": 0, "text": "old"}
            with self.assertRaises(ReadFailure):
                await service.export_report("old")
            exporter.assert_not_called()
        with self.assertRaises(ReadFailure):
            await service.generate_report("day; echo bad")
        await service.close()

    async def test_read_permissions_and_historical_statuses_survive_api(self):
        from main import Plugin
        plugin = Plugin()
        with patch.object(plugin.service, "generate_report", AsyncMock(side_effect=ReadFailure("permission_denied", "无权限"))):
            self.assertEqual((await plugin.get_report())["status"], "permission_denied")
        self.assertEqual((await plugin.export_report("unknown"))["status"], "report_expired")
        await plugin._unload()

    async def test_journal_uses_scoped_or_groups_extended_windows_and_drops_metadata(self):
        from storage_guard.journal import read_journal
        row = {**log("PM: suspend entry"), "_CMDLINE": "password=secret"}
        mock = AsyncMock(return_value=Output(0, json.dumps(row), ""))
        with patch("storage_guard.journal.run", mock):
            result = await read_journal("week")
            argv = mock.call_args.args[0]
            self.assertIn("--since=-7d", argv)
            self.assertIn("--lines=12000", argv)
            self.assertIn("_SYSTEMD_UNIT=systemd-suspend.service", argv)
            self.assertIn("UNIT=systemd-suspend.service", argv)
            self.assertIn("+", argv)
            self.assertNotIn("_CMDLINE", result["records"][0])
            await read_journal("all")
            self.assertFalse(any(a.startswith("--since") or a.startswith("--boot") for a in mock.call_args.args[0]))

    async def test_reader_pci_name_only_accepted_if_address_and_id_match(self):
        devices = [{"reader": {"pciAddress": "0000:03:00.0", "pciId": "10ec:525a", "model": None}}]
        with patch("storage_guard.hardware.run", AsyncMock(return_value=Output(0, "0000:03:00.0 SD Host controller [0805]: Realtek Reader [10ec:525a] (rev 01)", ""))):
            await enrich_readers(devices)
        self.assertEqual(devices[0]["reader"]["model"], "Realtek Reader")
        with patch("storage_guard.hardware.run", AsyncMock(side_effect=ReadFailure("missing_command", "lspci"))):
            await enrich_readers(devices)
        self.assertIsNone(devices[0]["reader"]["model"])
        self.assertIn("missing_command", devices[0]["reader"]["modelNote"])
