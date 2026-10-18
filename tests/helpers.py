from storage_guard.devices import discover


def node(name, **kwargs):
    return {"name": name, "kname": name, "path": f"/dev/{name}", "type": "disk",
            "size": 512110190592, "ro": False, "rm": False, "rota": False,
            "mountpoints": [], "maj:min": "8:0", **kwargs}


def sd_device():
    disk = node("mmcblk0", **{"maj:min": "179:0"}, children=[
        node("mmcblk0p1", type="part", fstype="ext4", **{"maj:min": "179:1"})])
    return discover({"blockdevices": [disk]}, {"filesystems": []}, {
        "mmcblk0": {"topology": "/sys/devices/pci0000:00/0000:03:00.0/mmc_host/mmc0/mmc0:aaaa/block/mmcblk0", "card_type": "SD"}
    })[0]


def usb_device(name="sda", port="2-1"):
    return discover({"blockdevices": [node(name, tran="usb")]}, {"filesystems": []}, {
        name: {"topology": f"/sys/devices/pci/usb2/{port}/{port}:1.0/host6/target6:0:0/6:0:0:0/block/{name}"}
    })[0]


def record(message, index=1, boot="current"):
    return {"MESSAGE": message, "_BOOT_ID": boot, "__REALTIME_TIMESTAMP": str(index * 1000000), "__CURSOR": f"{boot}-{index}"}
