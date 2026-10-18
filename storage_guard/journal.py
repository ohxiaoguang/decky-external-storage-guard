"""Read a bounded tail from explicit journal windows; report failures truthfully."""
import json
from .commands import run, require_success, ReadFailure

MAX_RECORDS = 6000
MAX_EVENTS = 500
WINDOWS = {"boot": ["--boot=0"], "day": ["--since=-24h"], "previous": ["--boot=-1"]}


async def read_journal(window: str) -> dict:
    if window not in WINDOWS:
        raise ReadFailure("invalid_request", "不支持的日志时间范围")
    # -k implies the current boot. Use its explicit transport filter so the 24h
    # window can span boots without silently dropping retained kernel history.
    output = await run(["journalctl", "_TRANSPORT=kernel", "--no-pager", "--output=json", "--all",
                        f"--lines={MAX_RECORDS}", *WINDOWS[window]])
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
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            if not isinstance(record, dict) or not isinstance(record.get("MESSAGE"), str):
                continue
            record["MESSAGE"] = record["MESSAGE"][:4096]
            records.append(record)
        except (ValueError, TypeError) as exc:
            raise ReadFailure("read_failed", "内核日志 JSON 格式无法解析") from exc
    if not records:
        return {"status": "no_history" if window == "previous" else "no_logs",
                "message": "该范围没有可读取的内核日志，无法据此判断设备正常", "records": [], "limited": False}
    return {"status": "ok", "message": "已读取内核日志", "records": records,
            "limited": len(records) >= MAX_RECORDS}
