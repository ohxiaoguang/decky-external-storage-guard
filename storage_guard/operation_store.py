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


class AuditStore:
    """Independent, bounded operation history; never use kernel messages as proof."""
    MAX_BYTES = 512 * 1024
    MAX_OPERATIONS = 50

    def __init__(self, directory=None):
        directory = directory if directory is not None else os.environ.get("DECKY_PLUGIN_RUNTIME_DIR")
        self.path = Path(directory) / "remount-audit.json" if directory else None

    def load(self):
        if not self.path:
            return {"status": "unavailable", "message": "Decky 插件运行目录未配置，操作审计不可用", "operations": [], "limited": False}
        try:
            if self.path.is_symlink():
                raise ValueError("audit symlink")
            with self.path.open(encoding="utf-8") as handle:
                data = handle.read(self.MAX_BYTES + 1)
            if len(data.encode("utf-8")) > self.MAX_BYTES:
                raise ValueError("audit limit")
            value = json.loads(data)
            if not isinstance(value, dict) or not isinstance(value.get("operations"), list) or len(value["operations"]) > self.MAX_OPERATIONS:
                raise ValueError("invalid audit")
            if any(not isinstance(op, dict) or not isinstance(op.get("operationId"), str) for op in value["operations"]):
                raise ValueError("invalid operation")
            value.update(status="ok", message="独立审计记录；running 表示结果未确认，不代表操作成功")
            return value
        except FileNotFoundError:
            return {"status": "no_records", "message": "尚无可读取的独立审计记录；旧版本未记录的操作无法追溯", "operations": [], "limited": False}
        except (OSError, ValueError):
            return {"status": "read_failed", "message": "独立操作审计无法读取；不代表没有执行过操作", "operations": [], "limited": False}

    def record(self, operation):
        from .report import Redactor
        if not self.path:
            raise OSError("Decky plugin runtime directory is unavailable")
        history = self.load()
        if history["status"] not in ("ok", "no_records"):
            raise OSError("Existing audit is unreadable; refusing to overwrite")
        redactor = Redactor([])
        clipped = False
        def scrub(value):
            nonlocal clipped
            if isinstance(value, str):
                clipped |= len(value) > 4096
                return redactor.text(value[:4096])
            if isinstance(value, list):
                return [scrub(v) for v in value]
            if isinstance(value, dict):
                return {k: scrub(v) for k, v in value.items()}
            return value
        entry = scrub(operation)
        # Boot IDs are correlation metadata, not disk serials.
        entry["bootId"] = operation.get("bootId")
        entry["operationId"] = operation["operationId"]
        entry["auditDetailsTruncated"] = clipped
        operations = [op for op in history["operations"] if op["operationId"] != entry["operationId"]] + [entry]
        limited = history.get("limited", False) or len(operations) > self.MAX_OPERATIONS
        operations = operations[-self.MAX_OPERATIONS:]
        while True:
            text = json.dumps({"operations": operations, "limited": limited}, ensure_ascii=False)
            if len(text.encode("utf-8")) <= self.MAX_BYTES:
                break
            if len(operations) <= 1:
                raise OSError("Operation exceeds audit size limit")
            operations.pop(0)
            limited = True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
