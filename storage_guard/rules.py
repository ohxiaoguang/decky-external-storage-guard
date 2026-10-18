"""Ordered pure classification rules; scope/ownership is handled separately."""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    kind: str
    severity: str
    summary: str
    pattern: str


RULES = (
    Rule("filesystem_check", "Error", "发现文件系统检查要求或日志中止；重挂载不能修复文件系统", r"filesystem check required|(?:run|requires?|needs?).*(?:fsck|file\s*system check)|(?:journal.*abort|abort.*journal)|\bemergency_ro\b"),
    Rule("cache_flush", "Error", "存储缓存刷新失败，可能有写入未完成", r"error.*writing Cache Flush bit|(?:cache|synchronize)\s+.*(?:flush|cache).*fail|failed.*(?:flush|synchronize cache)"),
    Rule("io_error", "Error", "设备发生实际读写失败", r"\bI/O error\b|\b(?:Buffer I/O|blk_update_request).*error|critical (?:medium|target) error|\bFAILED Result:"),
    Rule("filesystem", "Error", "文件系统报告错误", r"(?:EXT4-fs|exfat(?:-fs)?|ntfs3?|NTFS)(?:\s|\(|:).*(?:\berror\b|\bcorrupt|\bfail|\babort|\binconsistent)"),
    Rule("readonly", "Error", "文件系统已因异常切换为只读", r"(?:remounting|remounted|re-mounted|switching|forcing).*(?:read-only|readonly)|write.protect.*(?:error|unexpected)"),
    Rule("offline", "Error", "存储设备离线，内核无法继续访问", r"rejecting I/O to (?:offline|dead) device|device offline|offline device"),
    Rule("disconnect", "Info", "存储设备已断开；单凭此记录无法判断是否意外拔出", r"USB disconnect|mmc\d+: card .*removed"),
    Rule("initialization", "Error", "存储设备初始化或连接失败", r"error.*whil(?:st|e) initiali[sz]ing SD card|unable to enumerate USB device|device descriptor read.*error|device not accepting address"),
    Rule("tuning", "Warning", "SD 调谐失败并回退；此记录不能证明卡已损坏", r"\bTuning failed\b"),
    Rule("timeout", "Warning", "设备响应超时；是否恢复需结合后续日志判断", r"timed?\s*out|\btimeout\b|timing out"),
    Rule("reset", "Warning", "存储控制器正在重试或重置", r"reset (?:high|full|super|low).*USB device|resetting|uas_eh_|abort.*command|retrying"),
    Rule("crc", "Warning", "传输校验错误，可能影响稳定性", r"\bCRC\b|\berror -84\b|\bcrc error\b"),
    Rule("controller", "Warning", "存储控制器报告异常", r"\b(?:mmc\d+|scsi|uas)\b.*(?:\berror\b|\bfailed\b)|(?:mmcblk\d+).*\berror\b"),
    Rule("mount", "Info", "文件系统挂载变化（不代表修复）", r"(?:EXT4-fs|exfat(?:-fs)?|ntfs3?).*(?:mounted filesystem|unmounting filesystem|unmounted filesystem|re-mounted|remounted filesystem)"),
    Rule("recognized", "Info", "系统识别到存储设备", r"new .*SD(?:HC|XC)? card|mmcblk\d+: mmc\d+:|\[\w+\] Attached SCSI (?:removable )?disk"),
)

COMPILED = [(rule, re.compile(rule.pattern, re.IGNORECASE)) for rule in RULES]


def classify(message: str) -> Rule | None:
    # Mount options describe future policy, not an observed remount/error.
    if "segfault" in message.lower():
        return None
    for rule, pattern in COMPILED:
        if pattern.search(message):
            return rule
    return None
