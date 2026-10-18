"""User-confirmed UDisks transactions. No forced unmount, auth bypass or repairs."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time
from .commands import ReadFailure, run
from .devices import scan, sysfs_facts
from .events import BLOCK
from .journal import read_journal
from .suspend import ordered

FILESYSTEMS = {"ext4", "exfat", "ntfs", "ntfs3"}
DATA_TYPES = {"0fc63daf-8483-4772-8e79-3d69d8477de4",  # Linux filesystem data
              "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7",  # Microsoft basic data
              "0x83", "0x7", "0x07"}
MOUNT_ROOTS = ("/run/media/", "/media/", "/mnt/")
TOKEN_TTL = 120


def mount_options(part: dict, readonly: bool) -> list[str]:
    """Preserve only backend-whitelisted flags; never replay arbitrary options."""
    source = part["mounts"][0].get("options", "") if part["mounts"] else ""
    values = source.split(",")
    result = ["ro"] if readonly else []
    result.extend(flag for flag in ("nosuid", "nodev", "noexec") if flag in values)
    if part.get("filesystem") != "ext4":
        for key in ("uid", "gid", "umask", "fmask", "dmask"):
            matches = [v.split("=", 1)[1] for v in values if v.startswith(key + "=")]
            pattern = r"[0-9]{1,10}" if key in ("uid", "gid") else r"[0-7]{1,4}"
            if len(matches) == 1 and re.fullmatch(pattern, matches[0]) and int(matches[0]) <= 4294967294:
                value = str(int(matches[0])) if key in ("uid", "gid") else format(int(matches[0], 8), "04o")
                result.append(f"{key}={value}")
            elif matches or key in ("uid", "gid"):
                raise ReadFailure("unsupported_permissions", "无法确认非 Linux 文件系统的原挂载权限；为避免改变存档访问权限，禁止操作")
    return result


def current_readonly(part):
    # Live state only. Never request rw or override a filesystem's protections.
    return bool(part["readOnly"] or any(m["readOnly"] or "emergency_ro" in m.get("options", "").split(",") for m in part["mounts"]))


def allowed_mount(target: str) -> bool:
    # Reject traversal and alternative spellings rather than normalizing them.
    return bool(target and target.startswith(MOUNT_ROOTS) and
                all(p not in ("..", ".") for p in target.split("/")) and "//" not in target)


def hosts_plugin(target: str) -> bool:
    protected = [str(Path(__file__).resolve())]
    protected.extend(os.environ[key] for key in ("DECKY_PLUGIN_DIR", "DECKY_PLUGIN_RUNTIME_DIR", "DECKY_HOME") if os.environ.get(key))
    prefix = target.rstrip("/") + "/"
    return any(str(Path(p).resolve()) == target or str(Path(p).resolve()).startswith(prefix) for p in protected)


def eligibility(device: dict, part: dict, mounted: bool = True) -> str:
    """Empty string means eligible. This pure policy fails closed on missing facts."""
    if device.get("kind") not in ("SD", "USB HDD", "USB SSD", "Unknown"):
        return "仅允许已确认的 SD 或 USB 外部存储"
    info = device.get("sysfs", {})
    topology = device.get("topology", "")
    usb = bool(re.search(r"/usb\d+/\d+-\d+", topology))
    sd = info.get("card_type") == "SD" and "/mmc_host/" in topology
    if not (usb or sd) or info.get("card_type") == "MMC":
        return "缺少可确认的外部设备拓扑，禁止操作"
    if device.get("managementBlocked") or info.get("holders") != []:
        return "设备包含交换、加密、映射或占用关系，仅支持监控"
    if part.get("type") != "part" or part.get("path") == device.get("id"):
        return "仅支持普通数据分区，不对整盘执行操作"
    if part.get("filesystem") not in FILESYSTEMS or (part.get("partitionType") or "").lower() not in DATA_TYPES:
        return "仅支持可确认的 ext4 / exFAT / NTFS 数据分区（排除系统、EFI、交换等分区类型）"
    facts = part.get("sysfs", {})
    if not (str(info.get("diskseq", "")).isdigit() and part.get("uuid") and part.get("partitionUuid") and
            facts.get("partition", "").isdigit() and facts.get("holders") == [] and
            part.get("majorMinor") == facts.get("dev") and
            facts.get("topology", "").startswith(topology + "/")):
        return "缺少连接序号、分区标识或完整 sysfs 信息，禁止操作"
    for p in device.get("partitions", []):
        if p.get("sysfs", {}).get("holders") != []:
            return "设备的分区存在映射占用或无法确认占用关系，禁止操作"
        if any(not allowed_mount(m.get("target", "")) for m in p.get("mounts", [])):
            return "设备包含系统目录或非受支持目录上的挂载，禁止操作"
        if any(hosts_plugin(m["target"]) for m in p.get("mounts", [])):
            return "设备承载 Decky 插件或其运行数据，禁止重新挂载"
    mounts = part.get("mounts", [])
    if mounted and len(mounts) != 1:
        return "需要恰好一个挂载点；未挂载或多重挂载分区仅支持监控"
    if mounted:
        try:
            mount_options(part, False)
        except ReadFailure as exc:
            return str(exc)
    if not mounted and mounts:
        return "分区仍被挂载或已被其他程序重新挂载，已停止操作"
    return ""


def identity(device: dict, part: dict) -> str:
    return json.dumps({"disk": device["id"], "topology": device["topology"],
                       "diskseq": device["sysfs"]["diskseq"],
                       "path": part["path"], "number": part["majorMinor"], "size": part["size"],
                       "uuid": part["uuid"], "partuuid": part["partitionUuid"],
                       "parttype": part["partitionType"], "filesystem": part["filesystem"],
                       "partition": part["sysfs"]["partition"], "sysfs": part["sysfs"]["topology"]}, sort_keys=True)


def live_check(device: dict, part: dict) -> None:
    """Recheck sysfs and the actual block special file immediately before UDisks."""
    disk_facts, part_facts = sysfs_facts(device["name"]), sysfs_facts(part["name"])
    if (disk_facts.get("topology") != device["topology"] or
            disk_facts.get("diskseq") != device["sysfs"].get("diskseq") or
            disk_facts.get("holders") != [] or
            any(part_facts.get(key) != part["sysfs"].get(key) for key in ("dev", "partition", "topology")) or
            part_facts.get("holders") != []):
        raise ReadFailure("stale_target", "设备连接或分区身份已变化，请刷新后重试")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", part["name"]) or part["path"] != f'/dev/{part["name"]}':
        raise ReadFailure("invalid_target", "不是后端确认的规范分区路径")
    try:
        node = os.stat(part["path"], follow_symlinks=False)
    except FileNotFoundError as exc:
        raise ReadFailure("device_disconnected", "分区设备文件已消失，已停止操作") from exc
    except PermissionError as exc:
        raise ReadFailure("permission_denied", "没有确认分区设备信息的权限，禁止操作") from exc
    if not stat.S_ISBLK(node.st_mode) or f"{os.major(node.st_rdev)}:{os.minor(node.st_rdev)}" != part["majorMinor"]:
        raise ReadFailure("stale_target", "分区设备号不匹配，禁止操作")
    # Active swap files can live inside an otherwise ordinary data filesystem.
    for line in Path("/proc/swaps").read_text().splitlines()[1:]:
        fields = line.split()
        if not fields:
            continue
        source = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), fields[0])
        if source == part["path"] or any(source == m["target"] or source.startswith(m["target"].rstrip("/") + "/")
                                         for m in part["mounts"]):
            raise ReadFailure("device_busy", "分区正在提供交换空间，禁止重新挂载")


def filesystem_warnings(records: list[dict], part: dict, boot: str) -> list[str]:
    warnings = []
    patterns = (
        (r"\bemergency_ro\b", "检测到 emergency_ro：设备可能因错误进入紧急只读状态"),
        (r"(?:journal.*abort|abort.*journal)", "检测到文件系统 journal aborted / 日志中止证据"),
        (r"filesystem check required|(?:run|requires?|needs?).*(?:fsck|file\s*system check)|check.*required", "检测到 filesystem check required / 需要文件系统检查的证据"),
    )
    relevant = [r for r in ordered(records) if r.get("_BOOT_ID") == boot and part["name"] in BLOCK.findall(r.get("MESSAGE", ""))]
    last_mount = max((i for i, row in enumerate(relevant) if re.search(
        r"(?:EXT4-fs|exfat(?:-fs)?|ntfs3?).*(?:\bmounted filesystem|\bre-mounted|\bremounted filesystem)", row.get("MESSAGE", ""), re.I)), default=-1)
    for index, row in enumerate(relevant):
        for pattern, description in patterns:
            if re.search(pattern, row.get("MESSAGE", ""), re.I):
                context = "历史记录：后续观察到挂载，是否修复未确认" if index < last_mount else "日志故障证据：当前是否仍异常无法仅凭历史日志确认"
                warning = f"{context}；{description}"
                if warning not in warnings:
                    warnings.append(warning)
    if any("emergency_ro" in m.get("options", "").split(",") for m in part["mounts"]):
        warnings.append("挂载状态报告 emergency_ro")
    return warnings


@dataclass
class Grant:
    fingerprint: str
    disk: str
    path: str
    mounts: list[dict]
    expires: float


class Remounter:
    def __init__(self):
        self.grants: dict[str, Grant] = {}

    def decorate(self, devices: list[dict], records: list[dict], boot: str, readable: bool) -> None:
        now = time.monotonic()
        self.grants = {t: g for t, g in self.grants.items() if g.expires > now}
        for device in devices:
            for part in device["partitions"]:
                reason = eligibility(device, part)
                warnings = filesystem_warnings(records, part, boot)
                if not readable:
                    warnings.append("本次启动日志不可用或不完整，无法排除文件系统故障；重挂载不是修复")
                token = None
                if not reason and len(self.grants) < 256:
                    token = secrets.token_urlsafe(32)
                    self.grants[token] = Grant(identity(device, part), device["id"], part["path"], deepcopy(part["mounts"]), now + TOKEN_TTL)
                elif not reason:
                    reason = "刷新过于频繁，请稍后刷新重试"
                part["management"] = {"eligible": token is not None, "reason": reason,
                                      "token": token, "warnings": warnings}

    async def target(self, grant: Grant, mounted: bool) -> tuple[dict, dict]:
        devices, _, _ = await scan()
        for device in devices:
            if device["id"] != grant.disk:
                continue
            for part in device["partitions"]:
                if part["path"] != grant.path:
                    continue
                reason = eligibility(device, part, mounted)
                if reason or identity(device, part) != grant.fingerprint or (mounted and part["mounts"] != grant.mounts):
                    raise ReadFailure("stale_target", reason or "设备、分区身份或挂载信息已变化，请重新确认")
                live_check(device, part)
                return device, part
        raise ReadFailure("device_disconnected", "设备已断开、分区已变化或不再允许操作，未继续执行")

    async def command(self, argv, phase, result, progress):
        entry = {"phase": phase, "argv": argv, "startedAt": datetime.now(timezone.utc).timestamp() * 1000,
                 "finishedAt": None, "returncode": None, "stdout": "", "stderr": "", "status": "pending", "outputAvailable": False}
        result["commands"].append(entry)
        if progress:
            progress(result)
        try:
            entry["status"] = "running"
            output = await run(argv, timeout=20, limit=65536)
            entry.update(returncode=output.code, outputAvailable=True, stdout=output.stdout[:4096], stderr=output.stderr[:4096],
                         outputTruncated=len(output.stdout) > 4096 or len(output.stderr) > 4096)
            self.command_result(output, phase)
            entry["status"] = "returned_zero"
        except (ReadFailure, OSError) as exc:
            entry.update(status=getattr(exc, "status", "command_failed"), failure=str(exc)[:1000])
            raise
        finally:
            entry["finishedAt"] = datetime.now(timezone.utc).timestamp() * 1000
            if progress:
                progress(result)

    @staticmethod
    def observation(part):
        return {"observedAt": datetime.now(timezone.utc).timestamp() * 1000,
                "path": part["path"], "majorMinor": part["majorMinor"],
                "readOnly": part["readOnly"], "mounts": deepcopy(part["mounts"])}

    async def execute(self, token: str, boot: str, progress=None) -> dict:
        grant = self.grants.get(token) if isinstance(token, str) else None
        result = {"status": "invalid_target", "phase": "validation", "message": "设备操作授权无效、过期或已使用，请刷新后重新确认",
                  "detail": "", "partition": grant.path if grant else None, "unmounted": False,
                  "mounted": None, "warnings": [], "operationId": secrets.token_hex(12), "bootId": boot,
                  "startedAt": datetime.now(timezone.utc).timestamp() * 1000,
                  "method": "udisksctl unmount + mount (noninteractive; no force)",
                  "commands": [], "beforeUnmount": None, "afterUnmount": None, "afterMount": None}
        if not grant or grant.expires <= time.monotonic():
            return result
        # Consume all outstanding authorizations so double clicks and older views
        # cannot queue a second transaction against the same physical disk.
        self.grants.clear()
        try:
            if progress:
                progress(result)
            _, part = await self.target(grant, True)
            readonly = current_readonly(part)
            try:
                journal = await read_journal("boot")
                evidence = filesystem_warnings(journal["records"], part, boot)
                result["warnings"].extend(evidence)
                if journal["status"] != "ok" or journal["limited"]:
                    result["warnings"].append("日志不可用或不完整，无法排除其他文件系统故障")
            except ReadFailure as exc:
                result["warnings"].append(f"日志检查不可用：{exc}")
            # Reading logs can take time: revalidate mounts, diskseq and the block
            # node once more immediately before issuing the first mutation.
            _, before = await self.target(grant, True)
            readonly |= current_readonly(before)
            if readonly:
                result["warnings"].append("本次只读挂载，不尝试解除只读状态；重新挂载不修复文件系统")
            options = mount_options(before, readonly)
            result["beforeUnmount"] = self.observation(before)
            result["phase"] = "unmount"
            if progress:
                progress(result)
            await self.command(["udisksctl", "unmount", "-b", grant.path, "--no-user-interaction"], "unmount", result, progress)
            # A zero exit is not proof that the mount disappeared.
            result["unmounted"] = None
            result["phase"] = "verify_unmount"
            if progress:
                progress(result)
            # Verify disconnection/replacement and unexpected automount after
            # unmount; never mount a newly arrived disk reusing the same name.
            _, absent = await self.target(grant, False)
            result["afterUnmount"] = self.observation(absent)
            result["unmounted"] = True
            result["mounted"] = False
            result["phase"] = "mount"
            argv = ["udisksctl", "mount", "-b", grant.path, "--no-user-interaction"]
            if options:
                argv.extend(["--options", ",".join(options)])
            await self.command(argv, "mount", result, progress)
            result["phase"] = "verify"
            if progress:
                progress(result)
            _, actual = await self.target_after_mount(grant)
            result["afterMount"] = self.observation(actual)
            actual_options = mount_options(actual, readonly)
            actual_readonly = actual["readOnly"] or any(m["readOnly"] for m in actual["mounts"])
            if (readonly and not actual_readonly) or not set(options).issubset(actual_options):
                raise ReadFailure("verification_failed", "挂载已完成但未确认只读、权限或安全选项保持一致，请停止使用设备并核对系统状态")
            result["mounted"] = True
            result["status"] = "success"
            result["message"] = "已验证挂载 → 卸载 → 重新挂载；不依赖内核日志，也不代表文件系统已修复"
            if actual_readonly and not readonly:
                result["warnings"].append("挂载已完成，但当前为只读；请核对最新日志，不要继续写入")
        except (ReadFailure, OSError, ValueError, KeyError, TypeError) as exc:
            result["status"] = getattr(exc, "status", "verification_failed")
            result["message"] = ("安全卸载后未确认重新挂载成功；分区可能保持未挂载，请勿继续使用，查看原因" if result["unmounted"] else
                                 "重新挂载未完成，已停止；请检查原因和刷新后的真实状态")
            result["detail"] = str(exc)[:1000]
            if result["phase"] == "unmount" and result["status"] in ("timeout", "output_limit"):
                result["unmounted"] = None
                result["message"] = "卸载命令结果不确定，未继续挂载；请以刷新后的真实状态为准"
            if result["phase"] in ("mount", "verify"):
                result["mounted"] = None
        return result

    async def target_after_mount(self, grant):
        # Mountpoint can legitimately change under UDisks, so compare identity,
        # eligibility and live sysfs but not the original target path/options.
        devices, _, _ = await scan()
        for device in devices:
            for part in device["partitions"]:
                if device["id"] == grant.disk and part["path"] == grant.path:
                    reason = eligibility(device, part)
                    if reason or identity(device, part) != grant.fingerprint:
                        raise ReadFailure("verification_failed", reason or "挂载后的分区身份不匹配")
                    live_check(device, part)
                    return device, part
        raise ReadFailure("device_disconnected", "重新挂载后设备不可见")

    @staticmethod
    def command_result(output, phase):
        if output.code == 0:
            return
        detail = (output.stderr.strip() or output.stdout.strip())[:1000]
        lowered = detail.lower()
        status = f"{phase}_failed"
        if any(text in lowered for text in ("not authorized", "not authorised", "notauthorized", "authentication", "permission denied", "access denied", "not permitted", "polkit")):
            status = "permission_denied"
        elif any(text in lowered for text in ("busy", "in use")):
            status = "device_busy"
        elif any(text in lowered for text in ("no such device", "does not exist", "no such file", "error looking up object")):
            status = "device_disconnected"
        description = {"permission_denied": "权限不足，UDisks 未授权；不会绕过认证",
                       "device_busy": "设备正在使用，请先关闭使用该分区的程序",
                       "device_disconnected": "设备已断开或分区不存在"}.get(status, "安全卸载失败" if phase == "unmount" else "重新挂载失败")
        raise ReadFailure(status, f"{description}；udisksctl {phase}：{detail}")
