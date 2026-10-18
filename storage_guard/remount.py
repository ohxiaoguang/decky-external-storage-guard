"""Independent UDisks partition actions with identity and real-state verification."""
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
from .commands import ReadFailure, authorization_context, current_user, run
from .devices import scan, sysfs_facts
from . import udisks

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


def safe_mount_target(target):
    resolved = str(Path(target).resolve())
    return all(allowed_mount(path) and path != "/run/media/root" and not path.startswith("/run/media/root/")
               and not hosts_plugin(path) for path in (target, resolved))


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
        return "设备包含交换、加密、映射或占用关系，不可操作"
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
            return "设备承载 Decky 插件或其运行数据，禁止操作"
    mounts = part.get("mounts", [])
    if mounted and len(mounts) != 1:
        return "需要恰好一个挂载点；未挂载或多重挂载分区不可操作"
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
            raise ReadFailure("device_busy", "分区正在提供交换空间，禁止操作")


@dataclass
class Grant:
    fingerprint: str
    disk: str
    path: str
    mounts: list[dict]
    expires: float
    action: str
    options: list[str]
    actor: tuple


def desktop_options(user):
    return ["nosuid", "nodev", f"uid={user.pw_uid}", f"gid={user.pw_gid}"]


class PartitionManager:
    def __init__(self):
        self.grants = {}
        # Only options of this connection's verified unmount; no operation history.
        self.options = {}

    def decorate(self, devices):
        self.grants.clear()
        active = set()
        for device in devices:
            for part in device["partitions"]:
                part["actions"] = {}
                for action in ("unmount", "mount"):
                    reason = eligibility(device, part, action == "unmount")
                    options = []
                    if not reason:
                        fingerprint = identity(device, part)
                        active.add(fingerprint)
                        try:
                            user = current_user()
                            if action == "unmount":
                                options = mount_options(part, current_readonly(part))
                            else:
                                options = self.options.get(fingerprint)
                                if options is None:
                                    options = [] if part["filesystem"] == "ext4" else desktop_options(user)
                                options = list(options)
                                if current_readonly(part) and "ro" not in options:
                                    options.insert(0, "ro")
                        except ReadFailure as exc:
                            reason = str(exc)
                    token = None
                    if not reason and len(self.grants) < 256:
                        token = secrets.token_urlsafe(32)
                        self.grants[token] = Grant(fingerprint, device["id"], part["path"], deepcopy(part["mounts"]), time.monotonic() + TOKEN_TTL, action, options,
                                                   (user.pw_name, user.pw_uid, user.pw_gid, user.pw_dir))
                    elif not reason:
                        reason = "操作分区数量超过上限"
                    part["actions"][action] = {"token": token, "reason": reason}
        self.options = {k: v for k, v in self.options.items() if k in active}

    async def target(self, grant, mounted, original=False):
        devices, _, _ = await scan()
        for device in devices:
            for part in device["partitions"]:
                if device["id"] != grant.disk or part["path"] != grant.path:
                    continue
                reason = eligibility(device, part, mounted)
                if reason or identity(device, part) != grant.fingerprint or (original and part["mounts"] != grant.mounts):
                    raise ReadFailure("stale_target", reason or "设备身份或挂载状态已变化，请刷新")
                live_check(device, part)
                return device, part
        raise ReadFailure("device_disconnected", "设备已断开或不再允许操作")

    async def execute(self, action, token, progress=None):
        grant = self.grants.get(token) if isinstance(token, str) else None
        result = {"status": "invalid_target", "action": action, "phase": "validation", "target": None,
                  "message": "操作授权无效或已过期，请刷新", "returncode": None, "verified": False,
                  "startedAt": datetime.now(timezone.utc).timestamp() * 1000, "mounts": None, "readOnly": None}
        if action not in ("mount", "unmount") or not grant or grant.action != action or grant.expires <= time.monotonic():
            return result
        self.grants.clear()
        result["target"] = grant.path
        if progress:
            progress(result)
        try:
            user = current_user()
            if grant.actor != (user.pw_name, user.pw_uid, user.pw_gid, user.pw_dir):
                raise ReadFailure("stale_target", "Decky 用户身份已变化，请刷新后重试")
            _, part = await self.target(grant, action == "unmount", original=True)
            if action == "unmount" and grant.fingerprint not in self.options and len(self.options) >= 256:
                raise ReadFailure("unavailable", "当前会话可保留的安全挂载选项已达上限，未执行卸载")
            options = list(grant.options)
            if current_readonly(part) and "ro" not in options:
                options.insert(0, "ro")
            result["phase"] = action
            if progress:
                progress(result)
            path = await udisks.prepare(part, action, safe_mount_target, readonly="ro" in options)
            # Recheck after the read-only D-Bus lookups, immediately before the operation.
            await self.target(grant, action == "unmount", original=True)
            actor = current_user()
            if grant.actor != (actor.pw_name, actor.pw_uid, actor.pw_gid, actor.pw_dir):
                raise ReadFailure("stale_target", "Decky 用户身份已变化，未执行操作")
            argv = udisks.action_command(path, action, user, options)
            output = await run(argv, timeout=20, limit=65536)
            result.update(returncode=output.code, stdout=output.stdout[:1000], stderr=output.stderr[:1000])
            self.command_result(output, action)
            result["phase"] = "verify"
            if progress:
                progress(result)
            _, actual = await self.target(grant, action == "mount")
            result.update(mounts=deepcopy(actual["mounts"]), readOnly=current_readonly(actual))
            if action == "mount":
                drivers = {"ext4": {"ext4"}, "exfat": {"exfat", "fuse.exfat", "fuseblk"},
                           "ntfs": {"ntfs", "ntfs3", "fuseblk"}, "ntfs3": {"ntfs", "ntfs3", "fuseblk"}}
                if any(m.get("filesystem") not in drivers[actual["filesystem"]] for m in actual["mounts"]):
                    raise ReadFailure("verification_failed", "未确认实际挂载的文件系统类型，请核对状态")
                # Let UDisks/fstab choose legitimate custom paths. Never accept the
                # known wrong root-user automount path as a successful user mount.
                if any(m["target"] == "/run/media/root" or m["target"].startswith("/run/media/root/") for m in actual["mounts"]):
                    raise ReadFailure("verification_failed", "分区挂载到了 root 用户目录；未确认正确挂载，请核对实际路径")
                if not safe_mount_target(actual["mounts"][0]["target"]):
                    raise ReadFailure("verification_failed", "实际挂载路径未通过安全验证，请核对状态")
                if actual["mounts"][0]["target"] != udisks.mounted_path(output.stdout):
                    raise ReadFailure("verification_failed", "UDisks 返回路径与实际挂载路径不一致")
                actual_options = mount_options(actual, result["readOnly"])
                if not set(options).issubset(actual_options):
                    raise ReadFailure("verification_failed", "未确认挂载权限或只读保护，请核对实际状态")
            else:
                # Unmount is complete, but no power-off or physical eject occurred.
                self.options[grant.fingerprint] = options
            result.update(status="success", verified=True, message="已卸载" if action == "unmount" else "已挂载")
        except (ReadFailure, OSError, ValueError, KeyError, TypeError) as exc:
            result.update(status=getattr(exc, "status", "verification_failed"), message=str(exc)[:1000])
            if result["phase"] == "verify" or result["status"] in ("timeout", "output_limit"):
                result["status"] = "uncertain"
                result["message"] = "不确定：" + result["message"]
        if result["status"] == "permission_denied":
            result["message"] += "；后台无法进行交互认证。" + await authorization_context()
        result["finishedAt"] = datetime.now(timezone.utc).timestamp() * 1000
        return result

    @staticmethod
    def command_result(output, action):
        if output.code == 0:
            return
        detail = (output.stderr.strip() or output.stdout.strip())[:1000]
        lowered = detail.lower()
        status = action + "_failed"
        if any(s in lowered for s in ("not authorized", "not authorised", "notauthorized", "notauthorizedcanobtain", "authentication", "permission denied", "access denied", "not permitted", "polkit")):
            status, description = "permission_denied", "权限不足"
        elif any(s in lowered for s in ("busy", "in use")):
            status, description = "device_busy", "设备正在使用"
        elif any(s in lowered for s in ("no such device", "does not exist", "no such file", "error looking up object")):
            status, description = "device_disconnected", "设备已断开"
        else:
            description = "卸载失败" if action == "unmount" else "挂载失败"
        raise ReadFailure(status, description + ("：" + detail if detail else ""))
