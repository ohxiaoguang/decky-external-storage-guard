"""External identity comes from transport/sysfs, never block-device names alone."""
import json
import re
from pathlib import Path
from .commands import run, require_success, ReadFailure

LSBLK = ["lsblk", "--json", "--bytes", "--tree", "--output",
         "NAME,KNAME,PATH,TYPE,SIZE,MODEL,TRAN,RM,RO,ROTA,FSTYPE,MOUNTPOINTS,MAJ:MIN"]
FINDMNT = ["findmnt", "--json", "--list", "--output", "SOURCE,TARGET,FSTYPE,OPTIONS,MAJ:MIN"]
SYSTEM_MOUNTS = {"/", "/usr", "/var", "/home", "/boot", "/efi", "/boot/efi"}


def truth(value):
    return value is True or value == 1 or value == "1"


def sysfs_facts(name: str, root: Path = Path("/sys/class/block")) -> dict:
    base = root / name
    try:
        topology = str(base.resolve(strict=True))
    except (OSError, RuntimeError):
        topology = ""
    def read(relative):
        try:
            return (base / relative).read_text().strip()
        except OSError:
            return ""
    return {"topology": topology, "card_type": read("device/type"),
            "model": read("device/name") or read("device/model")}


def flatten(nodes):
    for node in nodes:
        yield node
        yield from flatten(node.get("children") or [])


def discover(lsblk: dict, mounts: dict, facts: dict[str, dict]) -> list[dict]:
    """Pure discovery with injectable sysfs facts; all mount instances are retained."""
    mount_rows = list(flatten(mounts.get("filesystems") or []))
    result = []
    for disk in lsblk.get("blockdevices") or []:
        if disk.get("type") != "disk":
            continue
        nodes = list(flatten([disk]))
        names = {n.get("path") or f'/dev/{n["kname"]}' for n in nodes}
        numbers = {n.get("maj:min") for n in nodes if n.get("maj:min")}
        relevant = [m for m in mount_rows if m.get("maj:min") in numbers or m.get("source", "").split("[")[0] in names]
        # Include mapped descendants: never present the running system disk as external.
        if any(m.get("target") in SYSTEM_MOUNTS for m in relevant) or any(
            p in SYSTEM_MOUNTS for n in nodes for p in n.get("mountpoints") or []
        ):
            continue
        name = disk.get("kname") or disk["name"]
        info = facts.get(name, {})
        topology = info.get("topology", "")
        usb = re.findall(r"/(\d+-\d+(?:\.\d+)*)(?:/|:)", topology)
        transport = (disk.get("tran") or "").lower()
        card_type = info.get("card_type", "").upper()
        is_usb = transport == "usb" or bool(usb)
        is_sd = card_type == "SD" and "/mmc_host/" in topology
        # eMMC is internal, including devices with misleading removable flags.
        if card_type == "MMC" or not (is_usb or is_sd):
            continue
        kind = "SD" if is_sd else "Unknown"
        if is_usb and disk.get("rota") is not None:
            kind = "USB HDD" if truth(disk["rota"]) else "USB SSD"
        parts = []
        for node in nodes:
            if node is not disk and node.get("type") != "part":
                continue
            path = node.get("path") or f'/dev/{node["kname"]}'
            matching = [m for m in relevant if (node.get("maj:min") and m.get("maj:min") == node["maj:min"])
                        or m.get("source", "").split("[")[0] == path]
            parts.append({
                "name": node.get("kname") or node["name"], "path": path,
                "size": int(node.get("size") or 0), "filesystem": node.get("fstype") or None,
                "readOnly": truth(node.get("ro")),
                "mounts": [{"target": m.get("target", ""), "filesystem": m.get("fstype"),
                            "readOnly": "ro" in (m.get("options") or "").split(",")} for m in matching],
            })
        controller = re.search(r"/mmc_host/(mmc\d+)(?:/|$)", topology)
        scsi = re.findall(r"/(\d+:\d+:\d+:\d+)(?:/|$)", topology)
        result.append({
            "id": disk.get("path") or f"/dev/{name}", "name": name,
            "model": (disk.get("model") or info.get("model") or "").strip(),
            "size": int(disk.get("size") or 0), "kind": kind,
            "transport": transport or None, "topology": topology,
            "controller": controller[1] if controller else None,
            "usbPort": usb[-1] if usb else None, "scsiAddress": scsi[-1] if scsi else None,
            "partitions": parts, "mounted": any(p["mounts"] for p in parts),
            "readOnly": any(p["readOnly"] or any(m["readOnly"] for m in p["mounts"]) for p in parts),
        })
    return result


async def scan() -> tuple[list[dict], list[str], list[str]]:
    raw = json.loads(require_success(await run(LSBLK), "lsblk"))
    warnings = []
    try:
        mounted = json.loads(require_success(await run(FINDMNT), "findmnt"))
    except (ReadFailure, ValueError) as exc:
        # Mount options are needed to distinguish read-only mounts from block RO.
        raise ReadFailure(getattr(exc, "status", "read_failed"), f"无法确认挂载状态：{exc}") from exc
    facts = {n["kname"]: sysfs_facts(n["kname"]) for n in raw.get("blockdevices", []) if n.get("kname")}
    devices = discover(raw, mounted, facts)
    external_names = {p["name"] for d in devices for p in d["partitions"]}
    excluded = [n.get("kname") for n in flatten(raw.get("blockdevices", []))
                if n.get("kname") and n["kname"] not in external_names]
    for name, info in facts.items():
        if name in excluded:
            controller = re.search(r"/mmc_host/(mmc\d+)(?:/|$)", info.get("topology", ""))
            if controller:
                excluded.append(controller[1])
    return devices, excluded, warnings
