import unittest
from storage_guard.suspend import pair_cycles, relation, annotate, history_payload, marker, ordered
from storage_guard.events import analyze
from helpers import sd_device


def log(message, mono=10, wall=1000, boot="boot-a", system=False, **extra):
    return {"MESSAGE": message, "_BOOT_ID": boot, "__MONOTONIC_TIMESTAMP": str(int(mono * 1_000_000)),
            "__REALTIME_TIMESTAMP": str(int(wall * 1_000_000)),
            "_TRANSPORT": "journal" if system else "kernel",
            **({"_SYSTEMD_UNIT": "systemd-suspend.service"} if system else {}), **extra}


def cycle_rows(boot="boot-a", offset=0):
    return [log("Performing sleep operation 'suspend'", 10 + offset, 1000 + offset, boot, True),
            log("PM: suspend entry (s2idle)", 11 + offset, 1001 + offset, boot),
            log("Freezing user space processes ...", 12 + offset, 1002 + offset, boot),
            log("PM: suspend exit", 13 + offset, 4603 + offset, boot),
            log("System returned from sleep operation", 14 + offset, 4604 + offset, boot, True)]


class SuspendTests(unittest.TestCase):
    def test_pair_preparing_kernel_entry_freezing_exit_and_systemd_completion(self):
        cycles = pair_cycles(cycle_rows())
        self.assertEqual(len(cycles), 1)
        cycle = cycles[0]
        self.assertEqual(cycle["status"], "paired")
        self.assertEqual(cycle["completion"], "systemd")
        self.assertEqual(cycle["start"]["timestamp"], 1000000)
        self.assertEqual(cycle["wake"]["timestamp"], 4604000)
        self.assertEqual(cycle["wallDurationSeconds"], 3604)
        self.assertTrue(cycle["estimated"])
        self.assertEqual(len(cycle["records"]), 5)

    def test_structured_unit_ids_work_with_localized_messages(self):
        rows = [log("正在启动系统挂起", 1, 1000, system=True, MESSAGE_ID="7d4958e842da4a758f6c1cdc7b36dcc5"),
                log("PM: suspend entry", 2, 1001), log("PM: suspend exit", 3, 2000),
                log("系统挂起服务已完成", 4, 2001, system=True, MESSAGE_ID="39f53479d3a045ac8e11786248231fbf")]
        self.assertEqual(pair_cycles(rows)[0]["completion"], "systemd")
        self.assertIsNone(marker(log("Finished System Suspend", system=False)))

    def test_multiple_cycles_and_duplicate_finish_not_double_counted(self):
        rows = cycle_rows() + [log("Finished System Suspend.", 15, 4605, system=True)] + cycle_rows(offset=100)
        cycles = pair_cycles(rows)
        self.assertEqual(len(cycles), 2)
        self.assertEqual(cycles[0]["wake"]["monotonicUs"], 15_000_000)
        self.assertNotEqual(cycles[0]["id"], cycles[1]["id"])

    def test_cross_boot_cycles_and_events_never_pair(self):
        rows = [log("PM: suspend entry", boot="boot-a"), log("PM: suspend exit", boot="boot-b")]
        cycles = pair_cycles(rows)
        self.assertEqual([c["status"] for c in cycles], ["missing_wake", "missing_start"])
        self.assertEqual(relation(log("I/O error, dev mmcblk0", 20, boot="boot-c"), cycles)["phase"], "unknown")

    def test_before_during_and_after_resume_are_distinct(self):
        cycles = pair_cycles(cycle_rows())
        self.assertEqual(relation(log("error", 9, 999), cycles)["phase"], "before_suspend")
        self.assertEqual(relation(log("error", 12.5, 4603), cycles)["phase"], "during_unknown")
        context = relation(log("error", 52, 4642), cycles)
        self.assertEqual(context["phase"], "after_wake")
        self.assertEqual(context["delaySeconds"], 38)
        self.assertTrue(context["estimated"])  # no source clock

    def test_suspend_time_not_added_to_post_resume_delta(self):
        cycles = pair_cycles(cycle_rows())
        context = relation(log("error", 52, 4642, _SOURCE_MONOTONIC_TIMESTAMP="52000000"), cycles)
        self.assertEqual(context["delaySeconds"], 38)
        self.assertFalse(context["estimated"])
        self.assertNotEqual(cycles[0]["wallDurationSeconds"], 4)

    def test_clock_jump_uses_monotonic_and_is_marked(self):
        cycles = pair_cycles(cycle_rows())
        context = relation(log("error", 52, 100, _SOURCE_MONOTONIC_TIMESTAMP="52000000"), cycles)
        self.assertEqual(context["delaySeconds"], 38)
        self.assertTrue(context["estimated"] and context["clockAdjusted"])

    def test_buffered_kernel_record_uses_source_clock_not_receipt(self):
        cycles = pair_cycles(cycle_rows())
        context = relation(log("error", 100, 4700, _SOURCE_MONOTONIC_TIMESTAMP="12500000"), cycles)
        self.assertEqual(context["phase"], "during_unknown")
        self.assertIsNone(context["delaySeconds"])

    def test_missing_mono_fallback_estimates_without_fabrication(self):
        rows = cycle_rows()
        for row in rows:
            row.pop("__MONOTONIC_TIMESTAMP")
        cycles = pair_cycles(rows)
        context = relation({"_BOOT_ID": "boot-a", "__REALTIME_TIMESTAMP": "4642000000"}, cycles)
        self.assertEqual(context["delaySeconds"], 38)
        self.assertTrue(context["estimated"])
        self.assertEqual(context["basis"], "realtimeUs")
        self.assertIsNone(relation({"_BOOT_ID": "boot-a"}, cycles)["delaySeconds"])

    def test_repeated_entry_does_not_make_old_incomplete_cycle_own_later_errors(self):
        rows = [log("PM: suspend entry", 1, 1)] + cycle_rows()
        cycles = pair_cycles(rows)
        self.assertEqual(len(cycles), 2)
        self.assertEqual(cycles[0]["status"], "missing_wake")
        self.assertEqual(relation(log("error", 52, 4642), cycles)["cycleId"], cycles[1]["id"])

    def test_abort_is_not_successful_sleep(self):
        rows = [log("Freezing user space processes", 1, 1), log("Failed to suspend", 2, 2, system=True)]
        cycles = pair_cycles(rows)
        self.assertEqual(cycles[0]["status"], "failed")
        self.assertIsNone(cycles[0]["wake"])
        self.assertEqual(relation(log("error", 5, 5), cycles)["phase"], "during_unknown")
        self.assertEqual(pair_cycles([rows[1]])[0]["status"], "failed")

    def test_before_next_suspend_can_also_be_after_previous_wake(self):
        cycles = pair_cycles(cycle_rows() + cycle_rows(offset=100))
        context = relation(log("error", 52, 4642), cycles)
        self.assertEqual(context["phase"], "after_wake")
        self.assertTrue(context["beforeNextSuspend"])

    def test_window_counts_1_5_10_minutes_and_reinitialization_signals(self):
        rows = cycle_rows()
        for delay, message in [(38, "mmc0: Tuning failed"), (60, "I/O error, dev mmcblk0"),
                               (300, "mmc0: CRC error"), (600, "mmc0: error -84"), (601, "mmc0: Tuning failed"),
                               (20, "mmc0: new UHS-I speed SDR104 SDXC card at address aaaa"),
                               (25, "EXT4-fs (mmcblk0p1): re-mounted filesystem r/w")]:
            rows.append(log(message, 14 + delay, 4604 + delay))
        events, _ = analyze(rows, [sd_device()], [], "boot-a")
        cycles = pair_cycles(rows)
        annotate(events, cycles)
        history = history_payload(cycles, events, {"status": "ok", "limited": False})
        self.assertEqual(history["cycles"][0]["afterCounts"], {"1": 2, "5": 3, "10": 4})
        self.assertIn("recognized", history["cycles"][0]["observations"])
        self.assertIn("mount", history["cycles"][0]["observations"])

    def test_unavailable_empty_incomplete_and_history_limit_are_distinct(self):
        self.assertEqual(history_payload([], [], {"status": "permission_denied"})["status"], "permission_denied")
        self.assertEqual(history_payload([], [], {"status": "ok"})["status"], "no_records")
        rows = sum((cycle_rows(offset=100 * i) for i in range(110)), [])
        history = history_payload(pair_cycles(rows), [], {"status": "ok"})
        self.assertEqual(len(history["cycles"]), 100)
        self.assertTrue(history["limited"])

    def test_no_boot_is_not_assigned_and_order_ignores_wall_clock_backstep(self):
        self.assertEqual(pair_cycles([{"MESSAGE": "PM: suspend entry"}]), [])
        rows = [log("later", 20, 10), log("earlier", 10, 100)]
        self.assertEqual([r["MESSAGE"] for r in ordered(rows)], ["earlier", "later"])
