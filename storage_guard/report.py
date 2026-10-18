"""UTF-8 reports with bounded raw diagnostic records and default redaction."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import secrets
from .suspend import marker, ordered, micros, cycle_timeline

MAX_REPORT_BYTES = 2 * 1024 * 1024
REPORT_WINDOWS = {"boot": "本次开机", "day": "最近24小时", "week": "最近7天", "all": "全部可用记录（有界尾部）"}


class Redactor:
    def __init__(self, devices, private_values=()):
        self.known = {}
        self.salt = secrets.token_bytes(16)
        for value in private_values:
            self.known[value] = self.alias("设备标识", value)
        for device in devices:
            for part in device["partitions"]:
                for key in ("uuid", "partitionUuid"):
                    if part.get(key):
                        self.known[part[key]] = self.alias("标识", part[key])
                for mount in part["mounts"]:
                    if mount.get("target"):
                        self.known[mount["target"]] = self.alias("挂载路径", mount["target"])

    def structured(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.structured(v) for v in value]
        if isinstance(value, dict):
            return {k: self.structured(v) for k, v in value.items()}
        return value

    def alias(self, kind, value):
        return f"[{kind}-{hashlib.sha256(self.salt + value.encode()).hexdigest()[:8]}]"

    def text(self, value):
        text = str(value)
        for original, replacement in sorted(self.known.items(), key=lambda pair: -len(pair[0])):
            text = text.replace(original, replacement)
        text = re.sub(r"(?i)\b(?:https?|ftp)://[^\s\"'<>]+", "[URL已隐藏]", text)
        text = re.sub(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9+/_.=-]+", r"\1 [已隐藏]", text)
        text = re.sub(r'''(?ix)\b(password|passwd|passphrase|(?:access|refresh|id)[_-]?token|token|secret|authorization|api[_-]?key|session[_-]?key|credential|serialnumber|serial(?:\s+number)?|wwn|cid)\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\n,;]+)''', lambda m: m[1] + "=[已隐藏]", text)
        text = re.sub(r"(?i)\b(?:SerialNumber|serial number)\s+[^\s,;]+", "SerialNumber=[已隐藏]", text)
        text = re.sub(r"/(?:home|run/media|media|mnt)/[^\s\]\)\"',;]+", lambda m: self.alias("用户路径", m[0]), text)
        text = re.sub(r"(?i)\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b", lambda m: self.alias("UUID", m[0]), text)
        text = re.sub(r"(?i)\b[0-9a-f]{16,}\b", lambda m: self.alias("长标识", m[0]), text)
        text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[邮箱已隐藏]", text)
        text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP已隐藏]", text)
        text = re.sub(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", "[MAC已隐藏]", text)
        user = os.environ.get("DECKY_USER")
        if user and len(user) >= 2:
            text = re.sub(r"(?<!\w)" + re.escape(user) + r"(?!\w)", "[用户]", text)
        return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)


def iso(timestamp_ms):
    if timestamp_ms is None:
        return "未知"
    try:
        return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return "时间戳超出可表示范围"


def record_key(row):
    return (str(row.get("_BOOT_ID", "")), str(row.get("__CURSOR", "")), str(row.get("__MONOTONIC_TIMESTAMP", "")),
            str(row.get("__REALTIME_TIMESTAMP", "")), row.get("MESSAGE", ""))


def wake_description(context):
    phase = context.get("phase")
    if phase == "after_wake":
        return f"唤醒后{'约' if context['estimated'] else ''}{context['delaySeconds']:.3f}秒 ({context['basis']})" + ("；也位于下一次休眠前" if context.get("beforeNextSuspend") else "")
    return {"before_suspend": "休眠前", "during_unknown": "休眠/恢复过程中，无法确定", "unknown": "缺少足够记录，无法关联唤醒"}.get(phase, "未知")


def build_report(snapshot, capture, hardware, generated_at=None, private_values=()):
    generated_at = generated_at or datetime.now(timezone.utc).timestamp() * 1000
    redactor = Redactor(snapshot["devices"], private_values)
    counts = Counter(e["severity"] for e in snapshot["events"])
    cycles = capture["cycles"]
    limits = ["仅读取内核及指定休眠服务，排除无关用户程序日志；不是全部系统日志。",
              "设备与控制器信息是报告生成时快照，历史启动不套用当前设备名归属。",
              "历史 journal aborted / fsck 等日志不证明当前仍异常；后续正常挂载也不证明已经修复。只读状态以实时块设备和挂载状态为准，不尝试解除文件系统保护。",
              "时间相关性不代表因果关系。挂起时 CLOCK_MONOTONIC 不走时；日志接收/转发可能延迟，时间差按字段标明估计。",
              "跨启动展示顺序使用日志实时时间；RTC 回退时不保证跨 Boot 的真实先后。启动内尽可能按单调时间排序。",
              "原始诊断消息仅做隐私脱敏与有界截断，并非逐字节未修改归档；没有记录不证明设备健康。",
              "脱敏保留设备路径、类型型号、PCI ID/驱动和本地总线端口用于诊断；常见序列号、UUID、用户路径和凭据会隐藏。分享前仍需人工检查。"]
    for label, status in (("设备扫描", snapshot["deviceStatus"]), ("日志读取", snapshot["journalStatus"])):
        limits.append(f"{label}: {status['status']} — {redactor.text(status['message'])}")
    limits.extend(redactor.text(w) for w in snapshot["warnings"])
    if snapshot["journalStatus"].get("limited"):
        limits.append("journal 读取条数、单条消息或事件列表达到上限；本报告不是该时间范围的全部历史。")
    if snapshot["window"] != "boot":
        boots = {r.get("_BOOT_ID") for r in capture["records"] if r.get("_BOOT_ID")}
        limits.append(f"历史保留范围未验证：本次范围读取到 {len(boots)} 个启动周期；未见更早启动可能是未发生、未持久保存或已轮转，不能保证覆盖整个所选时段。")
    if snapshot["window"] in ("week", "all"):
        limits.append("长时间范围仅取最多12000条所选日志的尾部，受12秒及8MiB命令输出上限约束；系统可能已轮转删除旧记录。")
    if not cycles:
        limits.append("未发现可配对的休眠记录；可能未休眠、记录缺失、窗口被截断或日志不可用，不能据此排除休眠。")
    if len(cycles) > 100:
        limits.append("休眠摘要仅列最近100个周期；原始消息仍按独立大小上限保留。")
    lines = ["External Storage Guard 诊断报告", f"生成时间 (UTC): {iso(generated_at)}",
             f"时间范围: {REPORT_WINDOWS.get(snapshot['window'], snapshot['window'])}",
             "", "=== 简短摘要 ===",
             f"当前外部设备 {len(snapshot['devices'])}；返回事件：严重 {counts['Error']} / 警告 {counts['Warning']} / 信息 {counts['Info']}；识别休眠周期 {len(cycles)}。",
             "唤醒后的异常只表示时间相关，不能证明休眠导致存储故障。",
             "", "=== 系统信息（当前） ===", f"系统: {redactor.text(hardware['os'])}",
             f"内核: {redactor.text(hardware['kernel'])}", f"设备型号: {redactor.text(hardware['model'] or '无法可靠识别')}",
             "", "=== 外部存储与读卡器（当前） ==="]
    for device in snapshot["devices"][:64]:
        lines.append(redactor.text(f"{device['name']} | {device['id']} | {device['model'] or '未知型号'} | {device['kind']} | {device['size']} bytes"))
        reader = device.get("reader")
        if reader:
            lines.append(redactor.text(f"  SD控制器 {reader['controller']} | 型号 {reader.get('model') or '未知（不根据PCI ID猜测名称）'} | PCI {reader.get('pciAddress') or '未知'} ID={reader.get('pciId') or '未知'} | 驱动 {reader.get('driver') or '未知'}"))
            if reader.get("modelNote"):
                limits.append(redactor.text(reader["modelNote"]))
        else:
            lines.append("  SD读卡器身份未确认（USB桥接不推断为原生SD控制器）。")
        for part in device["partitions"][:64]:
            mount_text = "; ".join(f"{m['target']} ({'ro' if m['readOnly'] else 'rw'})" for m in part["mounts"])
            lines.append(redactor.text(f"  {part['path']} | {part['size']} bytes | FS={part['filesystem'] or '未知'} | 块设备只读={part['readOnly']} | {mount_text or '未挂载'}"))
    if len(snapshot["devices"]) > 64 or any(len(d["partitions"]) > 64 for d in snapshot["devices"]):
        limits.append("设备/分区信息列表已截断至各64项。")
    lines.extend(["", "=== 诊断限制与隐私 ===", *limits, "", "=== 休眠历史（日志边界估计，UTC） ==="])
    for cycle in cycles[-100:]:
        lines.append(f"Boot={cycle['bootId']} Cycle={cycle['id']} {cycle['status']} 开始={iso(cycle['start']['timestamp'] if cycle['start'] else None)} 唤醒完成={iso(cycle['wake']['timestamp'] if cycle['wake'] else None)} 来源={cycle['completion'] or '缺失'}")
        lines.extend("  " + note for note in cycle["notes"])
    operation = capture.get("operation")
    lines.extend(["", "=== 插件主动操作（当前会话最近一次；非内核日志） ===",
                  "不持久保存操作历史；重启插件后无法追溯上次会话。系统挂载事件仍从 journal 读取。"])
    if operation:
        safe = redactor.structured(operation)
        safe["bootId"] = operation.get("bootId")
        lines.append(json.dumps(safe, ensure_ascii=False))
    else:
        lines.append("当前会话没有操作结果；不能据此判断上次会话是否完成操作。")
    event_map = {e["id"]: e for e in snapshot["events"]}
    lines.extend(["", "=== 各周期事件时间线（前5分钟 / 进入期间 / 后10分钟；仅已返回事件） ==="])
    for cycle in cycles[-100:]:
        lines.append(f"Boot={cycle['bootId']} Cycle={cycle['id']}；日志边界和时间关系均为估计，不代表因果")
        for item in cycle_timeline(cycle, cycles, snapshot["events"]):
            message = item.get("message", "") if item["source"] == "sleep" else event_map[item["eventId"]]["raw"]
            lines.append(f"  {iso(item['timestamp'])} monoUs={item['monotonicUs']} {item['phase']} {item['kind']} | {redactor.text(message)}")
    lines.extend(["", "=== 分类事件与唤醒时间关系 ==="])
    for event in snapshot["events"][::-1]:
        lines.append(f"{iso(event['timestamp'])} Boot={event['bootId'] or '未知'} {event['severity']} {event['kind']} 设备={event['deviceId'] or '未关联'} 引用={','.join(event['references'])} | {wake_description(event['wakeContext'])} | {redactor.text(event['summary'])}")
    # Context selection is independent of classifier matches: relevant successful
    # enumeration/controller messages are retained for future rule reanalysis.
    selected = {}
    for row in capture["contextRecords"]:
        selected[record_key(row)] = row
    for row in capture["records"]:
        if marker(row):
            selected[record_key(row)] = row
    raw = []
    for row in ordered(list(selected.values())):
        item = {key: row[key] for key in ("_BOOT_ID", "__REALTIME_TIMESTAMP", "__MONOTONIC_TIMESTAMP", "_SOURCE_REALTIME_TIMESTAMP", "_SOURCE_MONOTONIC_TIMESTAMP", "_TRANSPORT", "_SYSTEMD_UNIT", "UNIT", "SYSLOG_IDENTIFIER", "MESSAGE_ID", "messageTruncated") if key in row}
        item["MESSAGE"] = redactor.text(row["MESSAGE"])
        raw.append(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
    prefix = "\n".join(lines)
    # Reserve a visible truncation banner. Prefer the latest raw records while
    # preserving chronological order in the exported subset.
    base_truncated = len(prefix.encode("utf-8")) > 256 * 1024
    prefix = prefix.encode("utf-8")[:256 * 1024].decode("utf-8", errors="ignore")
    budget = MAX_REPORT_BYTES - len(prefix.encode("utf-8")) - 2048
    kept = []
    for line in reversed(raw):
        needed = len(line.encode("utf-8")) + 1
        if needed > budget:
            break
        kept.append(line)
        budget -= needed
    kept.reverse()
    truncated = base_truncated or len(kept) < len(raw) or snapshot["journalStatus"].get("limited", False) or len(cycles) > 100
    banner = f"报告截断: {'是' if truncated else '未触及本次读取/报告大小上限（不保证历史完整）'}；原始相关记录保留 {len(kept)}/{len(raw)}，上限2MiB。"
    text = banner + "\n" + prefix + "\n\n=== 完整原始诊断消息（脱敏 JSONL 子集，非分类摘要） ===\n" + "\n".join(kept) + "\n"
    summary = "\n".join(["External Storage Guard 简短诊断摘要", f"生成时间 (UTC): {iso(generated_at)}", *lines[4:7], banner,
                          f"日志状态: {snapshot['journalStatus']['status']}；会话最近操作: {operation.get('status') if operation else '无记录'}", "完整原始日志请复制完整报告或导出 TXT。", "\n".join(limits)])
    return {"text": text, "summary": summary, "generatedAt": generated_at, "truncated": bool(truncated),
            "size": len(text.encode("utf-8")), "rawCount": len(kept), "availableRawCount": len(raw)}
