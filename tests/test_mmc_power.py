import unittest
from storage_guard.events import analyze
from storage_guard.rules import classify
from storage_guard.suspend import pair_cycles, annotate, history_payload, cycle_timeline
from storage_guard.report import build_report
from test_suspend import log
from test_report import report_fixture, HARDWARE
from helpers import sd_device


def power_rows():
    return [log("mmc0: error -84 doing runtime suspend", 8, 998),
        log("PM: suspend entry (s2idle)", 10, 1000),
        log("mmc0: error -84 writing Cache Flush bit", 11, 1001),
        log("PM: suspend exit", 12, 4600),
        log("mmc0: error -84 writing Cache Enable bit", 13, 4601),
        log("mmc0: error -84 doing runtime resume", 14, 4602),
        log("mmc0: Tuning failed, falling back to fixed sampling clock", 15, 4603),
        log("mmc0: Tuning failed, falling back to fixed sampling clock", 16, 4604)]


class MmcPowerTests(unittest.TestCase):
    def parsed(self, rows=None):
        rows = rows or power_rows()
        events, _ = analyze(rows, [sd_device()], [], "boot-a")
        cycles = pair_cycles(rows)
        annotate(events, cycles)
        return rows, events, cycles

    def test_real_power_failures_have_distinct_classifications_before_crc(self):
        for message, kind in (("mmc0: error -84 writing Cache Flush bit", "cache_flush"),
                              ("mmc0: error -84 writing Cache Enable bit", "cache_enable"),
                              ("mmc0: error -84 doing runtime suspend", "runtime_suspend"),
                              ("mmc0: error -84 doing runtime resume", "runtime_resume")):
            self.assertEqual(classify(message).kind, kind)
            self.assertEqual(classify(message).severity, "Error")
        self.assertEqual(classify("mmc0: error -84 reading register").kind, "crc")

    def test_complete_bounded_timeline_includes_before_during_after_and_repeated_tuning(self):
        rows, events, cycles = self.parsed()
        timeline = cycle_timeline(cycles[0], cycles, events)
        self.assertEqual(len(timeline), len(rows))
        phases = {entry["kind"]: entry["phase"] for entry in timeline}
        self.assertEqual(phases["runtime_suspend"], "before_suspend")
        self.assertEqual(phases["cache_flush"], "during_unknown")
        self.assertEqual(phases["cache_enable"], "after_wake")
        self.assertEqual(sum(entry["kind"] == "tuning" for entry in timeline), 2)
        enable = next(event for event in events if event["kind"] == "cache_enable")
        self.assertEqual(enable["wakeContext"]["delaySeconds"], 1)
        self.assertTrue(enable["wakeContext"]["estimated"])
        history = history_payload(cycles, events, {"status": "ok"})
        self.assertEqual(history["cycles"][0]["timeline"], timeline)

    def test_buffered_flush_uses_source_time_and_is_not_declared_after_wake(self):
        rows = power_rows()
        rows[2] = log("mmc0: error -84 writing Cache Flush bit", 20, 4608, _SOURCE_MONOTONIC_TIMESTAMP="11000000")
        _, events, cycles = self.parsed(rows)
        flush = next(event for event in events if event["kind"] == "cache_flush")
        self.assertEqual(flush["wakeContext"]["phase"], "during_unknown")
        timeline = cycle_timeline(cycles[0], cycles, events)
        kinds = [entry["kind"] for entry in timeline]
        self.assertLess(kinds.index("cache_flush"), kinds.index("exit"))

    def test_cross_boot_runtime_errors_and_far_away_events_do_not_enter_cycle(self):
        rows, events, cycles = self.parsed(power_rows() + [
            log("mmc0: error -84 doing runtime resume", 13, 4601, boot="other"),
            log("mmc0: error -84 doing runtime resume", 900, 5500),
            {"MESSAGE": "mmc0: error -84 doing runtime suspend", "_BOOT_ID": "boot-a", "__REALTIME_TIMESTAMP": "1000000"}])
        timeline = cycle_timeline(cycles[0], cycles, events)
        self.assertEqual(len(timeline), 8)
        self.assertEqual(sum(item["kind"] == "runtime_resume" for item in timeline), 1)

    def test_report_includes_cycle_timeline_and_original_power_logs(self):
        rows, events, cycles = self.parsed()
        snapshot, capture = report_fixture()
        snapshot["events"] = events
        capture.update(records=rows, cycles=cycles, contextRecords=[row for row in rows if "mmc0:" in row["MESSAGE"]])
        text = build_report(snapshot, capture, HARDWARE)["text"]
        for message in ("writing Cache Flush bit", "writing Cache Enable bit", "doing runtime resume", "Tuning failed", "PM: suspend entry", "PM: suspend exit"):
            self.assertIn(message, text)
        self.assertIn("各周期事件时间线", text)
        self.assertIn("during_unknown", text)
        self.assertIn("不代表因果", text)
