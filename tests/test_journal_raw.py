import asyncio
import json
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
        self.assertIn("__REALTIME_TIMESTAMP=1000000", text)
        self.assertIn("__MONOTONIC_TIMESTAMP=1000", text)
        self.assertIn("_BOOT_ID=actual-boot", text)
        self.assertIn("_SYSTEMD_UNIT=udisks2.service", text)
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
        self.assertIn("_SOURCE_MONOTONIC_TIMESTAMP=123", result["text"])
        self.assertTrue(result["limited"])
        self.assertNotIn("__REALTIME_TIMESTAMP=0", result["text"])

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
