"""Bounded raw current-boot journal text. No grading, attribution or inference."""
import json
import re
from .commands import run, require_success, ReadFailure

MAX_RECORDS = 2000
MAX_TEXT_BYTES = 48 * 1024  # Entire displayed text fits the 64 KiB clipboard cap.
SLEEP_UNITS = ("systemd-suspend.service", "systemd-hibernate.service", "systemd-hybrid-sleep.service", "systemd-suspend-then-hibernate.service")
FIELDS = ("MESSAGE", "_BOOT_ID", "__REALTIME_TIMESTAMP", "__MONOTONIC_TIMESTAMP", "_SOURCE_REALTIME_TIMESTAMP",
          "_SOURCE_MONOTONIC_TIMESTAMP", "_TRANSPORT", "_SYSTEMD_UNIT", "UNIT", "SYSLOG_IDENTIFIER")
KERNEL_SCOPE = re.compile(r"\bmmc\d*\b|mmcblk|sdhci|usb|\buas\b|\bscsi\b|\bsd[a-z]+\b|\bI/O\b|blk_update_request|Buffer I/O|EXT4|exfat|ntfs|\bPM:|Freezing user space|Restarting tasks|suspend|resume", re.I)


def number(value):
    return int(value) if isinstance(value, (str, int)) and str(value).isdigit() else 0


async def read_journal():
    matches = ["_TRANSPORT=kernel"]
    for unit in (*SLEEP_UNITS, "udisks2.service"):
        matches.extend(["+", f"_SYSTEMD_UNIT={unit}", "+", f"UNIT={unit}"])
    for identifier in ("systemd-sleep", "udisksd"):
        matches.extend(["+", f"SYSLOG_IDENTIFIER={identifier}"])
    try:
        output = await run(["journalctl", *matches, "--boot=0", "--no-pager", "--output=json", "--all",
                            "--output-fields=" + ",".join(FIELDS), f"--lines={MAX_RECORDS}"], timeout=10, limit=4 * 1024 * 1024)
        text = require_success(output, "journalctl")
    except ReadFailure as exc:
        if exc.status == "output_limit":
            return {"status": "output_limit", "message": "日志已截断：读取输出超过上限，无法安全显示不完整 JSON", "text": "", "limited": True}
        raise
    records = []
    count, skipped = 0, False
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("not a journal object")
        except ValueError as exc:
            raise ReadFailure("read_failed", "journal JSON 无法解析") from exc
        count += 1
        message = row.get("MESSAGE")
        is_kernel = row.get("_TRANSPORT") == "kernel"
        if isinstance(message, str):
            if is_kernel and not KERNEL_SCOPE.search(message):
                continue
            raw = message
        elif isinstance(message, list):
            # Preserve the journal's binary MESSAGE representation, never invent text.
            raw = json.dumps(message, ensure_ascii=False)
        else:
            skipped = True
            continue
        fields = " ".join(f"{key}={row[key]}" for key in FIELDS if key != "MESSAGE" and key in row)
        records.append((number(row.get("__MONOTONIC_TIMESTAMP")), number(row.get("__REALTIME_TIMESTAMP")), fields + "\n" + raw + "\n"))
    records.sort(key=lambda row: (row[0], row[1]))
    kept, size = [], 0
    limited = count >= MAX_RECORDS or skipped
    for _, _, raw in reversed(records):
        amount = len(raw.encode("utf-8"))
        if size + amount > MAX_TEXT_BYTES:
            limited = True
            continue
        kept.append(raw)
        size += amount
    kept.reverse()
    return {"status": "ok" if records else "no_logs", "message": "日志已截断" if limited else ("" if records else "本次启动暂无可读取的相关日志"),
            "text": "".join(kept), "limited": limited}
