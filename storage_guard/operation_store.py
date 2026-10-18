"""Small atomic transaction record in Decky's own plugin runtime directory only."""
import json
import os
from pathlib import Path
import tempfile


class OperationStore:
    def __init__(self, directory=None):
        directory = directory if directory is not None else os.environ.get("DECKY_PLUGIN_RUNTIME_DIR")
        self.path = Path(directory) / "remount-state.json" if directory else None

    def load(self):
        if not self.path:
            return None
        try:
            with self.path.open() as handle:
                value = json.loads(handle.read(65536))
            if not isinstance(value, dict) or not isinstance(value.get("warnings"), list):
                raise ValueError("invalid operation record")
            for key, default in (("phase", "validation"), ("message", "上一次操作结果"), ("detail", ""), ("partition", None)):
                value.setdefault(key, default)
            if any(not isinstance(value.get(key), str) for key in ("status", "phase", "message", "detail")) or any(not isinstance(w, str) for w in value["warnings"]):
                raise ValueError("invalid operation fields")
            if value.get("status") == "running":
                value.update(status="interrupted", mounted=None, unmounted=None,
                             message="上一次重新挂载被中断，设备可能未挂载；请核对当前真实状态。不会自动重试或修复")
            return value
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            return {"status": "state_unavailable", "phase": "validation", "partition": None,
                    "message": "无法读取上一次操作记录，请核对真实挂载状态", "detail": "",
                    "warnings": [], "mounted": None, "unmounted": None}

    def save(self, value):
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(value, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
