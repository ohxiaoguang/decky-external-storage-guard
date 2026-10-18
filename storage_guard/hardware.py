"""Read model/type identifiers; disk identifiers are ephemeral redaction inputs only."""
import platform
from pathlib import Path
import re
from .commands import run, require_success, ReadFailure


def read_small(path):
    try:
        with Path(path).open() as handle:
            return handle.read(512).strip().replace("\x00", "")
    except (OSError, ValueError):
        return ""


def system_info():
    vendor = read_small("/sys/class/dmi/id/sys_vendor")
    product = read_small("/sys/class/dmi/id/product_name")
    valid = product and product.lower() not in ("default string", "to be filled by o.e.m.", "system product name")
    model = " ".join(v for v in (vendor, product) if v) if valid else ""
    if not model:
        model = read_small("/proc/device-tree/model")
    os_name = "未知系统"
    try:
        for line in Path("/etc/os-release").read_text()[:8192].splitlines():
            if line.startswith("PRETTY_NAME="):
                os_name = line.split("=", 1)[1].strip('"\'')
                break
    except OSError:
        pass
    return {"kernel": platform.release(), "model": model or None, "os": os_name}


def reader_info(topology, controller):
    if not controller:
        return None
    # Only the PCI function preceding a native MMC host is a reader candidate;
    # never present a USB xHCI host as the SD reader model.
    before = topology.split("/mmc_host/", 1)[0]
    addresses = re.findall(r"(?:^|/)([0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7])(?=/|$)", before, re.I)
    if not addresses:
        return {"controller": controller, "pciAddress": None, "pciId": None, "driver": None, "model": None}
    address = addresses[-1]
    base = Path("/sys/bus/pci/devices") / address
    vendor, device = read_small(base / "vendor"), read_small(base / "device")
    try:
        driver = (base / "driver").resolve(strict=True).name
    except OSError:
        driver = None
    return {"controller": controller, "pciAddress": address,
            "pciId": f"{vendor.removeprefix('0x')}:{device.removeprefix('0x')}" if vendor and device else None,
            "driver": driver, "model": None}


async def enrich_readers(devices):
    cache = {}
    for device in devices[:64]:
        reader = device.get("reader")
        if not reader or not reader.get("pciAddress"):
            continue
        address = reader["pciAddress"]
        if address not in cache and len(cache) < 8:
            model, note = None, None
            try:
                text = require_success(await run(["lspci", "-Dnn", "-s", address], timeout=2, limit=8192), "lspci")
                for line in text.splitlines():
                    if line.startswith(address + " ") and reader.get("pciId") and f"[{reader['pciId']}]" in line and ": " in line:
                        model = re.sub(r"\s+\[[0-9a-f]{4}:[0-9a-f]{4}\].*$", "", line.split(": ", 1)[1], flags=re.I)[:256]
                        break
            except ReadFailure as exc:
                note = f"PCI名称查询不可用：{exc.status}；PCI ID/驱动仍保留"
            cache[address] = (model, note)
        reader["model"], reader["modelNote"] = cache.get(address, (None, "读卡器名称查询达到数量上限"))


def private_identifiers(devices):
    """Collect only for in-memory redaction, never include these values in output."""
    values = set()
    for device in devices[:64]:
        base = Path("/sys/class/block") / device["name"] / "device"
        for key in ("serial", "cid", "wwid"):
            value = read_small(base / key)
            if len(value) >= 6:
                values.add(value)
        for parent in Path(device.get("topology", "")).parents:
            if re.fullmatch(r"\d+-\d+(?:\.\d+)*", parent.name):
                value = read_small(parent / "serial")
                if len(value) >= 6:
                    values.add(value)
    return values
