"""Pure event association. Never assign generic USB errors by proximity in time."""
import re
from .rules import classify, Rule
from .journal import MAX_EVENTS
from .suspend import ordered, micros

BLOCK = re.compile(r"(?<![\w/-])(?:/dev/)?(mmcblk\d+(?:p\d+)?|sd[a-z]+\d*|nvme\d+n\d+(?:p\d+)?)(?![\w])")
CONTROLLER = re.compile(r"\bmmc\d+(?=:|\b)")
PORT = re.compile(r"\busb (\d+-\d+(?:\.\d+)*)(?=[:\s])", re.I)
SCSI = re.compile(r"\b(?:sd|scsi) (\d+:\d+:\d+:\d+)\b")


def stamp(record):
    try:
        return int(record.get("__REALTIME_TIMESTAMP", 0)) / 1000
    except (ValueError, TypeError):
        return 0


def analyze(records: list[dict], devices: list[dict], excluded: list[str], boot_id: str,
            include_context: bool = False, max_events: int = MAX_EVENTS) -> tuple[list[dict], bool]:
    """Snapshot mappings only apply to the current boot; unknown history stays unassociated.

    To prevent older block names being assigned to replacement media, aliases
    seen before the last disconnect or attachment boundary are conservatively
    not assigned to snapshots. Historical USB driver evidence expires at removal.
    """
    current_devices = {d["id"]: d for d in devices}
    aliases = {p["name"]: d["id"] for d in devices for p in d["partitions"]}
    controllers = {}
    ports = {}
    scsi = {}
    for d in devices:
        if d.get("controller"):
            controllers.setdefault(d["controller"], []).append(d["id"])
        if d.get("usbPort"):
            ports.setdefault(d["usbPort"], []).append(d["id"])
        if d.get("scsiAddress"):
            scsi.setdefault(d["scsiAddress"], []).append(d["id"])
    # A block name or USB port can be reused within one boot. Do not attribute older
    # generations to today's device. Last disconnect is a boundary for snapshot data.
    rows = ordered(records)
    boundaries = {}
    for index, record in enumerate(rows):
        if record.get("_BOOT_ID") != boot_id:
            continue
        msg = record.get("MESSAGE", "")
        port = PORT.search(msg)
        if port and "usb disconnect" in msg.lower():
            for owner in ports.get(port[1], []):
                boundaries[owner] = index
        attach = re.search(r"\b(mmcblk\d+): (mmc\d+):", msg)
        if attach:
            owner = aliases.get(attach[1])
            if owner:
                boundaries[owner] = index
        disk_attach = re.search(r"\[([a-z]+)\] Attached SCSI (?:removable )?disk", msg)
        if disk_attach and aliases.get(disk_attach[1]):
            boundaries[aliases[disk_attach[1]]] = index

    events = []
    historical_ports = set()
    previous_boot = None
    for index, record in enumerate(rows):
        msg = record.get("MESSAGE", "")
        if include_context and "segfault" in msg.lower():
            continue
        if record.get("_BOOT_ID") != previous_boot:
            historical_ports.clear()
            previous_boot = record.get("_BOOT_ID")
        # Explicit mass-storage driver evidence survives unplugging for this
        # journal pass. Do not infer storage from generic USB enumeration.
        driver_port = re.search(r"\busb-storage\s+(\d+-\d+(?:\.\d+)*)(?=[:\s])", msg, re.I)
        if driver_port:
            historical_ports.add(driver_port[1])
        port = PORT.search(msg)
        if port and re.search(r"\b(?:uas|mass storage|usb-storage)\b", msg, re.I):
            historical_ports.add(port[1])
        rule = classify(msg) or (Rule("context", "Info", "存储原始上下文", "") if include_context else None)
        if not rule:
            continue
        names = set(BLOCK.findall(msg))
        current = bool(boot_id) and record.get("_BOOT_ID") == boot_id
        # Never show known internal/other block devices in external statistics.
        controller = CONTROLLER.search(msg)
        if current and (names.intersection(excluded) or (controller and controller[0] in excluded)):
            continue
        if current and any("pci:" + address in excluded for address in re.findall(r"\b[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]\b", msg, re.I)):
            continue
        if any(n.startswith("nvme") for n in names) and not (current and names.intersection(aliases)):
            continue
        address = SCSI.search(msg)
        candidates = set()
        if current:
            candidates.update(aliases[n] for n in names if n in aliases)
            if controller:
                candidates.update(controllers.get(controller[0], []))
            if port:
                candidates.update(ports.get(port[1], []))
            if address:
                candidates.update(scsi.get(address[1], []))
            for d in devices:
                reader = d.get("reader") or {}
                if reader.get("pciAddress") and re.search(r"(?<![\w:])" + re.escape(reader["pciAddress"]) + r"(?![\w.])", msg):
                    candidates.add(d["id"])
        # Ambiguity or records before the latest identity boundary must remain unassigned.
        owner = next(iter(candidates)) if len(candidates) == 1 else None
        if owner and index < boundaries.get(owner, -1):
            owner = None
        # Unknown USB traffic could be a mouse/controller. Require known storage
        # topology; standalone USB bus failures are deliberately excluded.
        storage_scope = bool(names or controller or address or re.search(r"\b(?:uas|sdhci(?:[-_]\w+)?|usb-storage)\b", msg, re.I))
        valid_snapshot_port = any(index >= boundaries.get(candidate, -1) for candidate in candidates)
        known_historical_port = bool(port and port[1] in historical_ports)
        if port and "usb disconnect" in msg.lower():
            historical_ports.discard(port[1])
        if port and not valid_snapshot_port and not storage_scope and not known_historical_port:
            continue
        if not storage_scope and not candidates and not known_historical_port:
            continue
        events.append({
            "id": str(record.get("__CURSOR") or f"{record.get('_BOOT_ID', '')}:{index}"),
            "timestamp": stamp(record) or None, "deviceId": owner,
            "deviceLabel": current_devices[owner]["name"] if owner else None,
            "references": sorted(names | ({controller[0]} if controller else set()) | ({port[1]} if port else set())),
            "bootId": record.get("_BOOT_ID"), "kind": rule.kind,
            "severity": rule.severity, "summary": rule.summary, "raw": msg,
            "realtimeUs": micros(record.get("__REALTIME_TIMESTAMP")),
            "monotonicUs": micros(record.get("__MONOTONIC_TIMESTAMP")),
            "sourceMonotonicUs": micros(record.get("_SOURCE_MONOTONIC_TIMESTAMP")),
            **({"record": record} if include_context else {}),
        })
    events.reverse()
    return events[:max_events], len(events) > max_events
