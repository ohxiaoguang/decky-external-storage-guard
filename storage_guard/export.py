"""Explicit exports to the Decky desktop user's Downloads, never arbitrary paths."""
from datetime import datetime, timezone
import os
from pathlib import Path
import pwd
import secrets
from .commands import ReadFailure


def desktop_user():
    name = os.environ.get("DECKY_USER")
    if not name:
        raise ReadFailure("export_unavailable", "无法确认 Decky 桌面用户，未向 root 目录导出")
    try:
        user = pwd.getpwnam(name)
    except KeyError as exc:
        raise ReadFailure("export_unavailable", "Decky 桌面用户不存在") from exc
    home = Path(user.pw_dir)
    configured = os.environ.get("DECKY_USER_HOME")
    if user.pw_uid == 0 or not home.is_absolute() or (configured and Path(configured) != home):
        raise ReadFailure("export_unavailable", "桌面用户目录或身份无法可靠确认")
    return home, user.pw_uid, user.pw_gid


def export_text(text, identity=None):
    home, uid, gid = identity if identity is not None else desktop_user()
    home = Path(home)
    descriptors = []
    file_fd = None
    file_name = None
    folder = None
    success = False
    try:
        folder = os.open(home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(folder)
        if os.fstat(folder).st_uid != uid:
            raise ReadFailure("export_unavailable", "用户主目录所有者不匹配，拒绝导出")
        for name in ("Downloads", "External-Storage-Guard"):
            created = False
            try:
                os.mkdir(name, mode=0o700, dir_fd=folder)
                created = True
            except FileExistsError:
                pass
            folder = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=folder)
            descriptors.append(folder)
            if created:
                if (os.fstat(folder).st_uid, os.fstat(folder).st_gid) != (uid, gid):
                    os.fchown(folder, uid, gid)
            if os.fstat(folder).st_uid != uid:
                raise ReadFailure("permission_denied", "导出目录所有者不是桌面用户")
        file_name = "External-Storage-Guard-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + secrets.token_hex(4) + ".txt"
        file_fd = os.open(file_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=folder)
        if (os.fstat(file_fd).st_uid, os.fstat(file_fd).st_gid) != (uid, gid):
            os.fchown(file_fd, uid, gid)
        data = text.encode("utf-8")
        with os.fdopen(file_fd, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(file_fd)
        actual = os.readlink(f"/proc/self/fd/{file_fd}")
        expected = str(home / "Downloads" / "External-Storage-Guard" / file_name)
        if actual != expected:
            raise ReadFailure("export_failed", "导出目录在操作中变化，已停止")
        success = True
        return {"path": actual, "size": len(data), "encoding": "UTF-8"}
    except PermissionError as exc:
        raise ReadFailure("permission_denied", "没有安全写入桌面用户导出目录的权限") from exc
    except OSError as exc:
        raise ReadFailure("export_failed", f"TXT 导出失败（目录、符号链接或空间问题）：{exc.strerror}") from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if not success and file_fd is not None and file_name and folder is not None:
            try:
                os.unlink(file_name, dir_fd=folder)
            except OSError:
                pass
        for descriptor in reversed(descriptors):
            os.close(descriptor)
