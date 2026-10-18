"""Read a bounded tail from explicit journal windows; report failures truthfully."""
import json
from .commands import run, require_success, ReadFailure

MAX_RECORDS = 6000
MAX_EVENTS = 500
WINDOWS = {"boot": ["--boot=0"], "day": ["--since=-24h"], "week": ["--since=-7d"], "all": [], "previous": ["--boot=-1"]}
SLEEP_UNITS = ("systemd-suspend.service", "systemd-hibernate.service", "systemd-hybrid-sleep.service", "systemd-suspend-then-hibernate.service")
FIELDS = ("MESSAGE", "_BOOT_ID", "__CURSOR", "__REALTIME_TIMESTAMP", "__MONOTONIC_TIMESTAMP",
          "_SOURCE_REALTIME_TIMESTAMP", "_SOURCE_MONOTONIC_TIMESTAMP", "_TRANSPORT", "_SYSTEMD_UNIT", "UNIT", "SYSLOG_IDENTIFIER", "MESSAGE_ID")


async def read_journal(window: str) -> dict:
    if window not in WINDOWS:
        raise ReadFailure("invalid_request", "不支持的日志时间范围")
    # -k implies the current boot. Use its explicit transport filter so the 24h
    # window can span boots without silently dropping retained kernel history.
    matches = ["_TRANSPORT=kernel"]
    for unit in SLEEP_UNITS:
        matches.extend(["+", f"_SYSTEMD_UNIT={unit}", "+", f"UNIT={unit}"])
    matches.extend(["+", "SYSLOG_IDENTIFIER=systemd-sleep"])
    count = 12000 if window in ("week", "all") else MAX_RECORDS
    output = await run(["journalctl", *matches, "--no-pager", "--output=json", "--all",
                        "--output-fields=" + ",".join(FIELDS), f"--lines={count}", *WINDOWS[window]], timeout=12)
    # A permissions hint must take precedence even when journalctl also reports
    # that an inaccessible boot cannot be found.
    if any(s in output.stderr.lower() for s in ("permission denied", "not seeing messages", "insufficient permissions", "access denied")):
        require_success(output, "journalctl")
    # No matching boot is different from a corrupt/unreadable journal.
    if window == "previous" and any(s in output.stderr.lower() for s in (
        "no such boot", "no journal boot entry", "no persistent journal", "no boot found",
        "cannot assign requested address", "failed to look up boot"
    )):
        return {"status": "no_history", "message": "系统未保留上一次启动的内核日志", "records": [], "limited": False}
    text = require_success(output, "journalctl")
    records = []
    shortened = False
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            if not isinstance(record, dict) or not isinstance(record.get("MESSAGE"), str):
                shortened = True
                continue
            clipped = len(record["MESSAGE"]) > 4096
            shortened |= clipped
            record = {key: record[key] for key in FIELDS if key in record}
            record["MESSAGE"] = record["MESSAGE"][:4096]
            if clipped:
                record["messageTruncated"] = True
            records.append(record)
        except (ValueError, TypeError) as exc:
            raise ReadFailure("read_failed", "内核日志 JSON 格式无法解析") from exc
    if not records:
        return {"status": "no_history" if window == "previous" else "no_logs",
                "message": "该范围没有可读取的内核日志，无法据此判断设备正常", "records": [], "limited": False}
    return {"status": "ok", "message": "已读取内核及休眠服务日志", "records": records,
            "limited": len(records) >= count or shortened, "recordCount": len(records), "recordLimit": count}
