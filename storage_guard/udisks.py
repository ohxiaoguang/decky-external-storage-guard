"""Fixed UDisks D-Bus operations; no terminal agent or caller-supplied method/path."""
import json
import os
import re
from .commands import ReadFailure, require_success, run

SERVICE = "org.freedesktop.UDisks2"
BASE = ["busctl", "--system", "--no-pager", "--json=short", "--timeout=20", "--allow-interactive-authorization=no"]


def decode(text, signature):
    try:
        value = json.loads(text)
        if value["type"] != signature:
            raise ValueError("unexpected signature")
        return value["data"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ReadFailure("read_failed", "UDisks 返回格式无法验证") from exc


def object_path(name):
    # Same escaping as udisks_safe_append_to_object_path, including underscore.
    return "/org/freedesktop/UDisks2/block_devices/" + "".join(c if c.isascii() and c.isalnum() else f"_{ord(c):02x}" for c in name)


async def prepare(part, action, valid_target, readonly=False):
    if os.getresuid() != (0, 0, 0):
        raise ReadFailure("permission_denied", "后台没有原生 UDisks 操作所需的受限特权；请重新加载插件，不会尝试终端认证或提权")
    output = await run(BASE + ["get-property", SERVICE, "/org/freedesktop/UDisks2/Manager", SERVICE + ".Manager", "Version"], limit=65536)
    version = decode(require_success(output, "UDisks 版本"), "s")
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[-.].*)?", version) if isinstance(version, str) else None
    # 2.10.0 introduced as-user. Also gate unmount to avoid leaving users unable
    # to mount again through this plugin on an unsupported daemon.
    if not match or tuple(map(int, match.groups())) < (2, 10, 0):
        raise ReadFailure("unsupported", "UDisks 未确认支持 as-user（需要 2.10.0 或更新）；未执行分区操作")
    path = object_path(part["name"])
    output = await run(BASE + ["call", SERVICE, path, "org.freedesktop.DBus.Properties", "GetAll", "s", SERVICE + ".Block"], limit=65536)
    data = decode(require_success(output, "UDisks 分区信息"), "a{sv}")
    try:
        props = data[0]
        major, minor = map(int, part["majorMinor"].split(":"))
        if (props["DeviceNumber"]["type"] != "t" or props["DeviceNumber"]["data"] != os.makedev(major, minor) or
                props["IdUUID"]["data"] != part["uuid"] or props["IdType"]["data"] != part["filesystem"]):
            raise ValueError("identity mismatch")
        configs = props["Configuration"]["data"]
        if not isinstance(configs, list):
            raise ValueError("invalid config")
        if action == "mount":
            for kind, values in configs:
                if kind != "fstab":
                    continue
                target = bytes(values["dir"]["data"]).rstrip(b"\0").decode("utf-8")
                if not valid_target(target):
                    raise ValueError("unsafe configured target")
                if readonly:
                    configured = bytes(values["opts"]["data"]).rstrip(b"\0").decode("utf-8").split(",")
                    if "ro" not in configured:
                        raise ValueError("fstab would ignore requested read-only option")
    except (KeyError, ValueError, TypeError, IndexError, UnicodeError) as exc:
        raise ReadFailure("stale_target", "UDisks 分区身份或系统配置的挂载目录未通过安全验证，未执行操作") from exc
    return path


def action_command(path, action, user, options):
    values = ["auth.no_user_interaction", "b", "true"]
    if action == "mount":
        values += ["as-user", "s", user.pw_name]
        if options:
            values += ["options", "s", ",".join(options)]
    return BASE + ["call", SERVICE, path, SERVICE + ".Filesystem", "Mount" if action == "mount" else "Unmount",
                   "a{sv}", str(len(values) // 3), *values]


def mounted_path(output):
    data = decode(output, "s")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], str):
        raise ReadFailure("verification_failed", "无法确认 UDisks 返回的挂载路径")
    return data[0]
