import asyncio
import json
import os
import time
from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, patch
from storage_guard.commands import Output, ReadFailure
from storage_guard.journal import read_journal, MAX_RECORDS, MAX_TEXT_BYTES
from storage_guard.service import Service


def row(message, stamp=1, kernel=True, **extra):
    return {"MESSAGE": message, "_BOOT_ID": "actual-boot", "__REALTIME_TIMESTAMP": str(stamp * 1000000),
            "__MONOTONIC_TIMESTAMP": str(stamp * 1000), "_TRANSPORT": "kernel" if kernel else "journal",
            **({} if kernel else {"_SYSTEMD_UNIT": "udisks2.service", "SYSLOG_IDENTIFIER": "udisksd"}), **extra}


class JournalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        zone = patch.dict(os.environ, {"TZ": "UTC"})
        zone.start(); time.tzset()
        self.addCleanup(time.tzset)
        self.addCleanup(zone.stop)

    async def read(self, records, stderr=""):
        output = Output(0, "\n".join(json.dumps(r) for r in records), stderr)
        with patch("storage_guard.journal.run", AsyncMock(return_value=output)) as command:
            result = await read_journal()
        return result, command

    async def test_includes_kernel_systemd_and_udisks_raw_with_exact_timestamps(self):
        messages = ["mmc0: Tuning failed, falling back to fixed sampling clock", "sdhci-pci: error -84",
            "usb 2-1: USB disconnect", "I/O error, dev sda", "EXT4-fs (mmcblk0p1): mounted filesystem r/w",
            "exfat (sda1): error", "ntfs3: sdb1: error", "scsi 6:0:0:0: Attached disk",
            "PM: suspend entry (s2idle)", "PM: suspend exit"]
        records = [row(message, index + 1) for index, message in enumerate(messages)] + [
            row("Unmounted /dev/sda1", 12, False),
            row("Finished System Suspend.", 11, False, _SYSTEMD_UNIT="systemd-suspend.service", SYSLOG_IDENTIFIER="systemd")]
        result, command = await self.read(records[::-1])
        text = result["text"]
        for message in messages + ["Unmounted /dev/sda1", "Finished System Suspend."]:
            self.assertIn(message, text)
        self.assertIn("1970-01-01 00:00:01.000 kernel: " + messages[0], text)
        self.assertIn("1970-01-01 00:00:12.000 udisksd: Unmounted /dev/sda1", text)
        for field in ("__REALTIME_TIMESTAMP", "__MONOTONIC_TIMESTAMP", "_BOOT_ID", "_TRANSPORT", "_SYSTEMD_UNIT"):
            self.assertNotIn(field, text)
        self.assertLess(text.index("Finished System Suspend."), text.index("Unmounted /dev/sda1"))
        self.assertNotIn("调谐", text)
        args = command.call_args.args[0]
        self.assertIn("_TRANSPORT=kernel", args)
        self.assertIn("_SYSTEMD_UNIT=udisks2.service", args)
        self.assertIn("UNIT=systemd-suspend.service", args)
        self.assertIn("--boot=0", args)
        self.assertNotIn("-k", args)
        self.assertNotIn("_CMDLINE", " ".join(args))
        self.assertEqual(command.call_args.kwargs["timeout"], 10)

    async def test_unrelated_kernel_not_included_and_message_not_rewritten(self):
        original = "mmc0: path=/run/media/private/Card\nTuning failed; token=raw-text"
        result, _ = await self.read([row("game.bin: segfault"), row("network unrelated"), row(original, 3)])
        self.assertIn(original, result["text"])
        self.assertNotIn("game.bin", result["text"])
        self.assertNotIn("network unrelated", result["text"])

    async def test_text_and_count_limits_are_explicit_and_keep_complete_messages(self):
        records = [row("mmc0: trace-%d " % i + "中" * 1000, i + 1) for i in range(40)]
        result, _ = await self.read(records)
        self.assertTrue(result["limited"])
        self.assertEqual(result["message"], "日志已截断")
        self.assertLessEqual(len(result["text"].encode()), MAX_TEXT_BYTES)
        self.assertIn("trace-39", result["text"])
        self.assertNotIn("trace-0 ", result["text"])
        self.assertTrue(result["text"].endswith("中" * 1000 + "\n"))
        result, _ = await self.read([row("unrelated", i) for i in range(MAX_RECORDS)])
        self.assertTrue(result["limited"])

    async def test_oversized_individual_message_and_binary_representation(self):
        result, _ = await self.read([row("mmc0: " + "x" * (MAX_TEXT_BYTES + 1)), row([1, 2, 255], 2)])
        self.assertTrue(result["limited"])
        self.assertIn("[1, 2, 255]", result["text"])
        self.assertNotIn("mmc0:", result["text"])

    async def test_empty_permissions_nonzero_invalid_json_and_output_cap(self):
        result, _ = await self.read([])
        self.assertEqual(result["status"], "no_logs")
        for output in (Output(0, "", "Permission denied"), Output(1, "", "journal corrupt"), Output(0, "{bad json", "")):
            with patch("storage_guard.journal.run", AsyncMock(return_value=output)), self.assertRaises(ReadFailure):
                await read_journal()
        with patch("storage_guard.journal.run", AsyncMock(side_effect=ReadFailure("output_limit", "cap"))):
            self.assertEqual((await read_journal())["message"], "日志已截断：读取输出超过上限，无法安全显示不完整 JSON")

    async def test_source_timestamp_and_missing_message_are_not_fabricated(self):
        result, _ = await self.read([row("mmc0: raw", _SOURCE_MONOTONIC_TIMESTAMP="123"), {"_BOOT_ID": "actual"}])
        self.assertIn("1970-01-01 00:00:01.000 kernel: mmc0: raw", result["text"])
        self.assertNotIn("_SOURCE_MONOTONIC_TIMESTAMP", result["text"])
        self.assertTrue(result["limited"])
        self.assertNotIn("__REALTIME_TIMESTAMP=0", result["text"])

    async def test_microsecond_timestamp_local_timezone_and_no_double_conversion(self):
        stamp = "1792341429557616"
        for zone, expected in (("UTC", "2026-10-18 16:37:09.557"), ("Asia/Shanghai", "2026-10-19 00:37:09.557")):
            with patch.dict(os.environ, {"TZ": zone}):
                result, _ = await self.read([row("mmc0: exact", __REALTIME_TIMESTAMP=stamp)])
            self.assertEqual(result["text"], expected + " kernel: mmc0: exact\n")

    async def test_dst_boundary_uses_system_timezone_rules(self):
        with patch.dict(os.environ, {"TZ": "America/New_York"}):
            before = int(datetime(2026, 3, 8, 6, 59, 59, tzinfo=timezone.utc).timestamp())
            result, _ = await self.read([row("mmc0: before", before), row("mmc0: after", before + 1)])
        self.assertIn("2026-03-08 01:59:59.000 kernel: mmc0: before", result["text"])
        self.assertIn("2026-03-08 03:00:00.000 kernel: mmc0: after", result["text"])

    async def test_order_uses_full_real_timestamp_before_formatting_not_monotonic_or_string_order(self):
        records = [row("mmc0: later", __REALTIME_TIMESTAMP="1000002", __MONOTONIC_TIMESTAMP="1"),
                   row("mmc0: first", __REALTIME_TIMESTAMP="9999999", __MONOTONIC_TIMESTAMP="5"),
                   row("mmc0: earlier", __REALTIME_TIMESTAMP="1000001", __MONOTONIC_TIMESTAMP="9")]
        result, _ = await self.read(records)
        self.assertLess(result["text"].index("earlier"), result["text"].index("later"))
        self.assertLess(result["text"].index("later"), result["text"].index("first"))

    async def test_missing_invalid_and_overflow_times_are_unknown_not_epoch_or_source_time(self):
        for stamp in (None, "", "broken", "1.5", -1, True, "9" * 30, [123]):
            result, _ = await self.read([row("mmc0: unknown", __REALTIME_TIMESTAMP=stamp, _SOURCE_REALTIME_TIMESTAMP="1000000")])
            self.assertEqual(result["text"], "未知时间 kernel: mmc0: unknown\n")
        result, _ = await self.read([{"MESSAGE": "mmc0: no timestamp", "_TRANSPORT": "kernel"}])
        self.assertTrue(result["text"].startswith("未知时间 kernel:"))

    async def test_simple_source_fallbacks_and_multiline_message_unchanged(self):
        original = "raw 中文\n  spaces retained\nlast line"
        result, _ = await self.read([row(original, kernel=False, SYSLOG_IDENTIFIER="udisksd"),
                                    {"MESSAGE": "sleep raw", "UNIT": "systemd-suspend.service"}])
        self.assertIn("udisksd: " + original + "\n", result["text"])
        self.assertIn("未知时间 systemd-suspend: sleep raw", result["text"])

    async def test_device_refresh_has_no_journal_dependency_and_unload_cancels_log_read(self):
        service = Service()
        with patch("storage_guard.service.scan", AsyncMock(return_value=([], [], []))), patch("storage_guard.service.read_journal", AsyncMock()) as journal:
            self.assertEqual((await service.snapshot())["deviceStatus"]["status"], "ok")
            journal.assert_not_called()
        started = asyncio.Event()
        async def blocked():
            started.set()
            await asyncio.Event().wait()
        with patch("storage_guard.service.read_journal", blocked):
            task = asyncio.create_task(service.logs())
            await started.wait()
            await service.close()
            with self.assertRaises(asyncio.CancelledError): await task
