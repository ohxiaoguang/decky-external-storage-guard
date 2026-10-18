"""Pure per-boot suspend pairing. Receipt clocks are not physical sleep timers."""
import hashlib
import re
from .journal import SLEEP_UNITS

MAX_CYCLES = 100


def micros(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, str)) and re.fullmatch(r"\d+", str(value)):
        return int(value)
    return None


def mono(row):
    return micros(row.get("_SOURCE_MONOTONIC_TIMESTAMP")) if micros(row.get("_SOURCE_MONOTONIC_TIMESTAMP")) is not None else micros(row.get("__MONOTONIC_TIMESTAMP"))


def realtime(row):
    return micros(row.get("__REALTIME_TIMESTAMP"))


def ordered(records):
    """Keep boots isolated; sort within a boot by monotonic if complete."""
    groups = {}
    for row in records:
        boot = row.get("_BOOT_ID")
        if isinstance(boot, str) and boot:
            groups.setdefault(boot, []).append(row)
    result = []
    for _, rows in sorted(groups.items(), key=lambda pair: min((realtime(r) for r in pair[1] if realtime(r) is not None), default=0)):
        use_mono = all(mono(r) is not None for r in rows)
        result.extend(sorted(rows, key=lambda r: ((mono(r) if use_mono else realtime(r)) or 0, realtime(r) or 0)))
    result.extend(sorted((r for r in records if not isinstance(r.get("_BOOT_ID"), str) or not r.get("_BOOT_ID")), key=lambda r: realtime(r) or 0))
    return result


def marker(row):
    message = row.get("MESSAGE", "")
    if not isinstance(message, str):
        return None
    system = row.get("_SYSTEMD_UNIT") in SLEEP_UNITS or row.get("UNIT") in SLEEP_UNITS or row.get("SYSLOG_IDENTIFIER") == "systemd-sleep"
    if re.search(r"\bPM: suspend entry\b", message):
        return "entry"
    if "Freezing user space processes" in message:
        return "freezing"
    if re.search(r"\bPM: suspend exit\b", message):
        return "exit"
    if system:
        # Stable IDs from systemd sd-messages.h, independent of localized text.
        structured = {"7d4958e842da4a758f6c1cdc7b36dcc5": "preparing",
                      "39f53479d3a045ac8e11786248231fbf": "returned",
                      "be02cf6855d2428ba40df7e9d022f03d": "failed"}.get(row.get("MESSAGE_ID"))
        if structured:
            return structured
        if re.search(r"failed|failure|cancelled|canceled", message, re.I):
            return "failed"
        if re.search(r"System returned from sleep|Finished .*?(?:Suspend|Hibernate|Sleep)|sleep operation.*finished|Woke up from", message, re.I):
            return "returned"
        if re.search(r"Entering sleep state|Performing sleep operation|Starting .*?(?:Suspend|Hibernate|Sleep)", message, re.I):
            return "preparing"
    return None


def point(row):
    value = realtime(row)
    return {"timestamp": value / 1000 if value is not None else None,
            "realtimeUs": value, "monotonicUs": mono(row)}


def pair_cycles(records):
    cycles = []
    groups = {}
    for row in ordered(records):
        if isinstance(row.get("_BOOT_ID"), str) and row["_BOOT_ID"]:
            groups.setdefault(row["_BOOT_ID"], []).append(row)
    for boot, rows in groups.items():
        active = None
        last = None
        for row in rows:
            kind = marker(row)
            if not kind:
                continue
            if kind == "entry" and active and active["hasEntry"]:
                active["notes"].append("重复休眠开始，前一周期缺少唤醒完成记录")
                active = None
            if kind in ("entry", "preparing", "freezing"):
                if active is None or active["wake"]:
                    key = f"{boot}:{row.get('__CURSOR', '')}:{mono(row)}:{realtime(row)}:{row['MESSAGE']}"
                    active = {"id": hashlib.sha256(key.encode()).hexdigest()[:20], "bootId": boot,
                              "start": point(row), "wake": None, "kernelWake": None, "hasEntry": False,
                              "status": "missing_wake", "completion": None, "estimated": True, "notes": [], "records": []}
                    cycles.append(active)
                active["hasEntry"] |= kind == "entry"
            elif kind == "returned" and active is None and last and last["wake"]:
                a, b = mono(row), last["wake"]["monotonicUs"]
                if a is not None and b is not None and 0 <= a - b <= 10_000_000:
                    last["records"].append(row)
                    last["wake"] = point(row)
                    continue
            if active is None:
                if kind not in ("exit", "returned", "failed"):
                    continue
                key = f"{boot}:{row.get('__CURSOR', '')}:{mono(row)}:{realtime(row)}"
                active = {"id": hashlib.sha256(key.encode()).hexdigest()[:20], "bootId": boot,
                          "start": None, "wake": None, "kernelWake": None, "hasEntry": False,
                          "status": "missing_start", "completion": None, "estimated": True, "notes": ["缺少休眠开始记录"], "records": []}
                cycles.append(active)
            active["records"].append(row)
            if kind in ("exit", "returned"):
                active["wake"] = point(row)
                active["completion"] = "systemd" if kind == "returned" else "kernel"
                if kind == "exit":
                    active["kernelWake"] = point(row)
                active["status"] = "paired" if active["start"] else "missing_start"
                if kind == "returned":
                    last, active = active, None
            elif kind == "failed":
                active["status"] = "failed"
                active["notes"].append("服务报告失败，不能确认真正进入休眠")
                last, active = active, None
        # A kernel exit without a service completion is only a kernel boundary.
    for cycle in cycles:
        if not cycle["hasEntry"]:
            cycle["notes"].append("缺少 PM suspend entry，准备阶段不证明已进入休眠")
        if cycle["completion"] == "kernel":
            cycle["notes"].append("只有内核退出标记，用户空间恢复完成时间未知")
        start, wake = cycle["start"], cycle["wake"]
        cycle["wallDurationSeconds"] = None
        if start and wake and start["realtimeUs"] is not None and wake["realtimeUs"] is not None:
            delta = (wake["realtimeUs"] - start["realtimeUs"]) / 1_000_000
            if delta >= 0:
                cycle["wallDurationSeconds"] = delta
            else:
                cycle["notes"].append("实时时钟发生回退，不能估计休眠时长")
        cycle["notes"].append("时间为日志边界估计；CLOCK_MONOTONIC 不包含挂起时长，实时时钟可能调整或日志可能延迟")
    return cycles


def relation(row, cycles):
    boot = row.get("_BOOT_ID")
    candidates = [c for c in cycles if c["bootId"] == boot]
    value = mono(row)
    use_mono = value is not None and all((not c["start"] or c["start"]["monotonicUs"] is not None) and
                                       (not c["wake"] or c["wake"]["monotonicUs"] is not None) for c in candidates)
    key = "monotonicUs" if use_mono else "realtimeUs"
    value = value if use_mono else realtime(row)
    unknown = {"phase": "unknown", "cycleId": None, "delaySeconds": None, "estimated": True, "basis": key, "beforeNextSuspend": False}
    if value is None or not candidates:
        return unknown
    last_wake, next_start, latest_start = None, None, None
    for cycle in candidates:
        start = cycle["start"][key] if cycle["start"] else None
        wake = cycle["wake"][key] if cycle["wake"] else None
        if start is not None and start <= value and (latest_start is None or start > latest_start["start"][key]):
            latest_start = cycle
        if wake is not None and wake <= value and (last_wake is None or wake > last_wake["wake"][key]):
            last_wake = cycle
        if start is not None and value < start and (next_start is None or start < next_start["start"][key]):
            next_start = cycle
    if latest_start:
        wake = latest_start["wake"][key] if latest_start["wake"] else None
        if (wake is not None and value <= wake) or (wake is None and (last_wake is None or latest_start["start"][key] > last_wake["wake"][key])):
            return {**unknown, "phase": "during_unknown", "cycleId": latest_start["id"]}
    if last_wake:
        delta = (value - last_wake["wake"][key]) / 1_000_000
        # Without a kernel source clock, delivery can lag; never present a receipt
        # delta as a measured physical resume interval.
        wall = realtime(row)
        anchor_wall = last_wake["wake"]["realtimeUs"]
        adjusted = use_mono and wall is not None and anchor_wall is not None and abs((wall - anchor_wall) / 1_000_000 - delta) > 2
        estimated = not use_mono or row.get("_SOURCE_MONOTONIC_TIMESTAMP") is None or last_wake["completion"] != "systemd" or adjusted
        return {"phase": "after_wake", "cycleId": last_wake["id"], "delaySeconds": delta,
                "estimated": estimated, "basis": key, "beforeNextSuspend": next_start is not None, "clockAdjusted": bool(adjusted)}
    if next_start:
        return {**unknown, "phase": "before_suspend", "cycleId": next_start["id"]}
    return unknown


def annotate(events, cycles):
    for event in events:
        event["wakeContext"] = relation({"_BOOT_ID": event["bootId"],
            "__REALTIME_TIMESTAMP": event.get("realtimeUs"), "__MONOTONIC_TIMESTAMP": event.get("monotonicUs"),
            "_SOURCE_MONOTONIC_TIMESTAMP": event.get("sourceMonotonicUs")}, cycles)


def history_payload(cycles, events, journal_status):
    limited = len(cycles) > MAX_CYCLES
    selected = cycles[-MAX_CYCLES:][::-1]
    result = []
    for cycle in selected:
        entry = {k: v for k, v in cycle.items() if k != "records"}
        entry["records"] = [{**point(r), "message": r["MESSAGE"][:1024], "kind": marker(r)} for r in cycle["records"][-8:]]
        entry["traceLimited"] = len(cycle["records"]) > 8 or any(len(r["MESSAGE"]) > 1024 for r in cycle["records"])
        after = [e for e in events if e["wakeContext"]["cycleId"] == cycle["id"] and e["wakeContext"]["phase"] == "after_wake"]
        entry["afterCounts"] = {str(minutes): sum(e["severity"] != "Info" and e["wakeContext"]["delaySeconds"] <= minutes * 60 for e in after) for minutes in (1, 5, 10)}
        entry["observations"] = sorted({e["kind"] for e in after if e["wakeContext"]["delaySeconds"] <= 600 and e["kind"] in ("recognized", "initialization", "disconnect", "reset", "mount")})
        result.append(entry)
    return {"cycles": result, "limited": limited or journal_status.get("limited", False),
            "status": journal_status["status"] if journal_status["status"] != "ok" else ("ok" if cycles else "no_records"),
            "message": "仅显示已保留日志中的记录；时间相关性不代表因果关系，计数仅覆盖返回事件"}
