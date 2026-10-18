"""Bounded raw current-boot journal text. No grading, attribution or inference."""
import json
import asyncio
import os
from datetime import datetime
import time
import re
from .commands import run, require_success, ReadFailure, process_context

MAX_RECORDS = 2000
MAX_TEXT_BYTES = 48 * 1024  # Entire displayed text fits the 64 KiB clipboard cap.
SLEEP_UNITS = ("systemd-suspend.service", "systemd-hibernate.service", "systemd-hybrid-sleep.service", "systemd-suspend-then-hibernate.service")
FIELDS = ("MESSAGE", "__REALTIME_TIMESTAMP", "__MONOTONIC_TIMESTAMP",
          "_TRANSPORT", "_SYSTEMD_UNIT", "UNIT", "SYSLOG_IDENTIFIER")
KERNEL_SCOPE = re.compile(r"\bmmc\d*\b|mmcblk|sdhci|usb|\buas\b|\bscsi\b|\bsd[a-z]+\b|\bI/O\b|blk_update_request|Buffer I/O|EXT4|exfat|ntfs|\bPM:|Freezing user space|Restarting tasks|suspend|resume", re.I)


def number(value):
    return int(value) if isinstance(value, (str, int)) and not isinstance(value, bool) and len(str(value)) <= 20 and str(value).isdigit() else None


def local_timestamp(microseconds):
    if microseconds is not None:
        try:
            seconds, remainder = divmod(microseconds, 1000000)
            # Exactly one conversion, in the device's local timezone. Avoid float
            # microsecond rounding; preserve milliseconds to distinguish nearby records.
            return datetime.fromtimestamp(seconds).replace(microsecond=remainder).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        except (OSError, OverflowError, ValueError):
            pass
    return "未知时间"


def source(row):
    identifier = row.get("SYSLOG_IDENTIFIER")
    if isinstance(identifier, str) and identifier and not any(c in identifier for c in "\r\n"):
        return identifier
    if row.get("_TRANSPORT") == "kernel":
        return "kernel"
    unit = row.get("_SYSTEMD_UNIT") or row.get("UNIT")
    return unit.removesuffix(".service") if isinstance(unit, str) and unit else "未知来源"


def service_matches():
    matches = []
    for unit in (*SLEEP_UNITS, "udisks2.service"):
        for field in ("_SYSTEMD_UNIT", "UNIT"):
            if matches: matches.append("+")
            matches.append(f"{field}={unit}")
    for identifier in ("systemd-sleep", "udisksd"):
        matches.extend(["+", f"SYSLOG_IDENTIFIER={identifier}"])
    return matches


def parse_rows(text):
    rows = []
    for line in text.splitlines():
        if not line.strip(): continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict): raise ValueError("not an object")
            rows.append(row)
        except ValueError as exc:
            raise ReadFailure("read_failed", "journal JSON 无法解析") from exc
    return rows


async def query(matches, lines=MAX_RECORDS, grep=None, probe=False):
    argv = ["journalctl", *matches, "--boot=0", "--no-pager", "--output=json", "--all",
            "--output-fields=" + ",".join((*FIELDS, "__CURSOR", "_BOOT_ID")), f"--lines={lines}"]
    if grep: argv += ["--grep=" + grep, "--case-sensitive=no"]
    output = await run(argv, timeout=2 if probe else 8, limit=128 * 1024 if probe else 2 * 1024 * 1024)
    # With --grep, journalctl uses exit 1 for no matching entries. Other errors
    # (including permission hints) must still be checked before treating it as empty.
    if grep and output.code == 1 and not output.stdout.strip() and not output.stderr.strip():
        return []
    return parse_rows(require_success(output, "journalctl"))


def records_from(rows):
    records, seen, skipped = [], set(), False
    for row in rows:
        key = row.get("__CURSOR") or json.dumps(row, sort_keys=True, ensure_ascii=False)
        if key in seen: continue
        seen.add(key)
        message = row.get("MESSAGE")
        if isinstance(message, str):
            if row.get("_TRANSPORT") == "kernel" and not KERNEL_SCOPE.search(message): continue
            raw = message
        elif isinstance(message, list): raw = json.dumps(message, ensure_ascii=False)
        else:
            skipped = True
            continue
        stamp = number(row.get("__REALTIME_TIMESTAMP"))
        monotonic = number(row.get("__MONOTONIC_TIMESTAMP"))
        records.append(((stamp is None, stamp or 0, monotonic or 0), f"{local_timestamp(stamp)} {source(row)}: {raw}\n"))
    records.sort(key=lambda record: record[0])
    return records, skipped


async def read_available():
    primary = await asyncio.gather(query(["_TRANSPORT=kernel"], grep=KERNEL_SCOPE.pattern), query(service_matches()), return_exceptions=True)
    for value in primary:
        if isinstance(value, Exception):
            if isinstance(value, ReadFailure) and value.status == "permission_denied":
                raise ReadFailure(value.status, str(value) + "；" + process_context()) from value
            raise value
    kernel, services = primary
    time.tzset()
    records, skipped = records_from(kernel + services)
    limited = skipped or len(kernel) >= MAX_RECORDS or len(services) >= MAX_RECORDS or len(records) > MAX_RECORDS
    notice = ""
    diagnostics = []
    if not records:
        comparisons = [([], None), (["_TRANSPORT=kernel"], None),
                       (["_TRANSPORT=kernel"], r"mmc|sdhci|EXT4|exfat|ntfs|I/O"),
                       (["_SYSTEMD_UNIT=udisks2.service", "+", "SYSLOG_IDENTIFIER=udisksd"], None),
                       (["_TRANSPORT=kernel", "+", *service_matches()], None)]
        results = await asyncio.gather(*(query(m, lines=20, grep=g, probe=True) for m, g in comparisons), return_exceptions=True)
        names = ("当前启动", "kernel", "MMC/文件系统", "UDisks", "原完整查询")
        diagnostics = [f"{name}={len(rows)}条" if isinstance(rows, list) else f"{name}={getattr(rows, 'status', '读取失败')}" for name, rows in zip(names, results)]
        # Only scope-specific comparison results may become displayed log text.
        recovered = []
        for index in (2, 3):
            if isinstance(results[index], list): recovered += results[index]
        records, extra_skipped = records_from(recovered)
        limited |= extra_skipped
        detail = "；".join(diagnostics) + "；" + process_context()
        if any(isinstance(value, ReadFailure) and value.status == "permission_denied" for value in results) or os.geteuid() != 0:
            raise ReadFailure("permission_denied", "无法确认系统 journal 的完整访问权限；" + detail)
        if records:
            notice, limited = "主查询为空，已显示有界对照查询恢复的相关记录；" + detail, True
        elif any(isinstance(value, Exception) for value in results):
            raise ReadFailure("read_failed", "journal 对照查询有异常，不能判定为没有日志；" + detail)
        elif kernel or services:
            return {"status": "filtered_empty", "message": "查询有记录但筛选后为空，不能判定系统无日志；" + detail, "text": "", "limited": limited}
        elif not results[0]:
            return {"status": "journal_unavailable", "message": "本次启动 journal 不可确认：全部有界对照查询为空；" + detail, "text": "", "limited": limited}
        else:
            return {"status": "no_logs", "message": "本次启动日志可读取，但未找到匹配的存储记录；" + detail, "text": "", "limited": limited}
    if os.geteuid() != 0:
        notice = "当前非特权进程仅显示可访问记录，不能确认系统 journal 完整；" + process_context()
    kept, size = [], 0
    for _, raw in reversed(records[-MAX_RECORDS:]):
        amount = len(raw.encode("utf-8"))
        if size + amount > MAX_TEXT_BYTES:
            limited = True
            continue
        kept.append(raw); size += amount
    kept.reverse()
    message = ("日志已截断" if limited else "") + (("；" if limited else "") + notice if notice else "")
    return {"status": "ok", "message": message, "text": "".join(kept), "limited": limited}


async def read_journal():
    try:
        return await asyncio.wait_for(read_available(), timeout=10)
    except (TimeoutError, asyncio.TimeoutError) as exc:
        raise ReadFailure("timeout", "journal 查询及有界对照读取超过 10 秒，不能判定为无日志") from exc
    except ReadFailure as exc:
        if exc.status == "output_limit":
            return {"status": "output_limit", "message": "日志已截断：读取输出超过上限，无法安全显示不完整 JSON", "text": "", "limited": True}
        raise
