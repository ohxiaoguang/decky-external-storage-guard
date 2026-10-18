"""Bounded query comparisons distinguish invisible, unmatched and filtered logs."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch
from storage_guard.commands import Output, ReadFailure
from storage_guard.journal import read_journal
from test_journal_raw import row


def output(rows):
    return Output(0, "\n".join(map(json.dumps, rows)), "")


class JournalAccessTests(unittest.IsolatedAsyncioTestCase):
    async def read(self, primary=([], []), comparisons=None, uid=0):
        comparisons = comparisons or [[], [], [], [], []]
        outputs = [value if isinstance(value, (Exception, Output)) else output(value) for value in (*primary, *comparisons)]
        async def respond(*args, **kwargs):
            value = outputs.pop(0)
            if isinstance(value, Exception): raise value
            return value
        with patch("storage_guard.journal.os.geteuid", return_value=uid), patch(
                "storage_guard.journal.run", AsyncMock(side_effect=respond)) as command:
            result = await read_journal()
        return result, command

    async def test_successful_empty_matching_queries_are_no_logs_only_with_readable_control(self):
        unrelated = row("desktop application message", kernel=False)
        result, command = await self.read(comparisons=[[unrelated], [], [], [], []])
        self.assertEqual(result["status"], "no_logs")
        self.assertEqual(result["text"], "")
        self.assertIn("当前启动=1条", result["message"])
        self.assertEqual(command.call_count, 7)
        probes = command.call_args_list[2:]
        self.assertTrue(all("--lines=20" in call.args[0] and call.kwargs["timeout"] == 2 and call.kwargs["limit"] == 128 * 1024 for call in probes))
        self.assertNotIn("_TRANSPORT=kernel", probes[0].args[0])
        self.assertIn("_TRANSPORT=kernel", probes[1].args[0])
        self.assertTrue(any(v.startswith("--grep=mmc|") for v in probes[2].args[0]))
        self.assertIn("_SYSTEMD_UNIT=udisks2.service", probes[3].args[0])
        self.assertIn("_TRANSPORT=kernel", probes[4].args[0])
        self.assertIn("_SYSTEMD_UNIT=systemd-suspend.service", probes[4].args[0])

    async def test_all_empty_queries_cannot_establish_journal_availability(self):
        result, _ = await self.read()
        self.assertEqual(result["status"], "journal_unavailable")
        self.assertNotIn("暂无可读取", result["message"])
        self.assertIn("UID=", result["message"])

    async def test_returned_rows_filtered_to_empty_are_explicit_not_healthy(self):
        result, _ = await self.read(primary=([row("unrelated network event")], []))
        self.assertEqual(result["status"], "filtered_empty")
        self.assertIn("筛选后为空", result["message"])

    async def test_partial_journal_permission_hint_even_exit_zero_is_not_empty(self):
        for rows in ([], [row("mmc0: visible subset")]):
            with self.assertRaises(ReadFailure) as caught:
                await self.read(primary=(Output(0, output(rows).stdout,
                    "Hint: You are currently not seeing messages from other users and the system."), []))
            self.assertEqual(caught.exception.status, "permission_denied")

    async def test_nonroot_own_messages_cannot_prove_access_to_system_journal(self):
        with self.assertRaises(ReadFailure) as caught:
            await self.read(comparisons=[[row("own messages", kernel=False)], [], [], [], []], uid=1000)
        self.assertEqual(caught.exception.status, "permission_denied")
        result, _ = await self.read(primary=([row("mmc0: accessible")], []), uid=1000)
        self.assertEqual(result["status"], "ok")
        self.assertIn("不能确认系统 journal 完整", result["message"])
        self.assertIn("mmc0: accessible", result["text"])

    async def test_control_permission_failure_is_not_reported_as_no_matching_logs(self):
        with self.assertRaises(ReadFailure) as caught:
            await self.read(comparisons=[ReadFailure("permission_denied", "denied"), [], [], [], []])
        self.assertEqual(caught.exception.status, "permission_denied")

    async def test_query_errors_are_not_reported_as_empty(self):
        with self.assertRaises(ReadFailure) as caught:
            await self.read(comparisons=[ReadFailure("timeout", "slow"), [], [], [], []])
        self.assertEqual(caught.exception.status, "read_failed")

    async def test_recovery_uses_only_related_probes_not_general_control_messages(self):
        result, _ = await self.read(comparisons=[[row("private unrelated", kernel=False)],
            [row("unrelated kernel")], [row("mmc0: raw recovered")],
            [row("Mounted /dev/mmcblk0p1", kernel=False)], []])
        self.assertEqual(result["status"], "ok")
        self.assertIn("mmc0: raw recovered", result["text"])
        self.assertIn("Mounted /dev/mmcblk0p1", result["text"])
        self.assertNotIn("private unrelated", result["text"])
        self.assertNotIn("unrelated kernel", result["text"])
        self.assertIn("对照查询恢复", result["message"])

    async def test_grep_selection_runs_in_journal_before_tail_limit(self):
        # The older related entry must not be lost by taking the latest 2000
        # unrelated kernel messages first. Model journal's grep-before-lines.
        entries = [row("mmc0: older storage error")] + [row("unrelated network", i + 2) for i in range(2100)]
        async def journal(argv, **kwargs):
            if "_TRANSPORT=kernel" not in argv: return output([])
            import re
            pattern = next((arg.removeprefix("--grep=") for arg in argv if arg.startswith("--grep=")), None)
            filtered = [r for r in entries if not pattern or re.search(pattern, r["MESSAGE"], re.I)]
            limit = int(next(arg.removeprefix("--lines=") for arg in argv if arg.startswith("--lines=")))
            return output(filtered[-limit:])
        with patch("storage_guard.journal.os.geteuid", return_value=0), patch("storage_guard.journal.run", journal):
            result = await read_journal()
        self.assertIn("mmc0: older storage error", result["text"])

    async def test_journal_grep_no_matches_exit_one_is_distinct_from_failure(self):
        result, _ = await self.read(primary=(Output(1, "", ""), []), comparisons=[[row("general", kernel=False)], [], [], [], []])
        self.assertEqual(result["status"], "no_logs")
        with self.assertRaises(ReadFailure):
            await self.read(primary=(Output(1, "", "invalid regular expression"), []))

    async def test_primary_failure_waits_for_other_bounded_query(self):
        finished = asyncio.Event()
        async def journal(argv, **kwargs):
            if "_TRANSPORT=kernel" in argv:
                raise ReadFailure("permission_denied", "denied")
            await asyncio.sleep(0)
            finished.set()
            return output([])
        with patch("storage_guard.journal.run", journal), self.assertRaises(ReadFailure):
            await read_journal()
        self.assertTrue(finished.is_set())
