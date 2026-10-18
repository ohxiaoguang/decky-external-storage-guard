"""Bounded, cancellable subprocesses. Commands and arguments are backend-owned."""
import asyncio
import os
import pwd
from dataclasses import dataclass
from pathlib import Path


class ReadFailure(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Output:
    code: int
    stdout: str
    stderr: str


def current_user():
    """Validate Decky's desktop account separately from the actual D-Bus caller."""
    try:
        account = pwd.getpwnam(os.environ.get("DECKY_USER", ""))
        if (account.pw_name != os.environ.get("DECKY_USER") or account.pw_uid <= 0 or account.pw_gid <= 0 or not Path(account.pw_dir).is_absolute() or
                account.pw_dir in ("/", "/root") or os.environ.get("DECKY_USER_HOME") != account.pw_dir or
                pwd.getpwuid(account.pw_uid).pw_name != account.pw_name):
            raise ValueError("invalid desktop account")
        uid, gid = os.getuid(), os.getgid()
        if os.getresuid() != (uid,) * 3 or os.getresgid() != (gid,) * 3:
            raise ValueError("mixed process credentials")
        if uid == 0:
            if gid != 0:
                raise ValueError("unexpected privileged group")
        elif uid != account.pw_uid or gid != account.pw_gid or os.environ.get("HOME") != account.pw_dir:
            raise ValueError("process does not match host user")
        return account
    except (KeyError, ValueError, OSError) as exc:
        raise ReadFailure("permission_denied", "无法确认 Decky 用户与后端身份；请重新加载插件") from exc


def process_context():
    return f"UID={os.getuid()}/EUID={os.geteuid()} GID={os.getgid()} groups={','.join(map(str, os.getgroups()))} tty={os.isatty(0)}"


async def authorization_context():
    detail = process_context()
    try:
        output = await run(["loginctl", "show-session", "self", "--no-pager", "-p", "Id", "-p", "User", "-p", "Active", "-p", "Seat"], timeout=2, limit=4096)
        detail += "; logind=" + (output.stdout.strip().replace("\n", ", ") if output.code == 0 else "当前后台进程无可确认的登录会话")
    except (ReadFailure, OSError):
        detail += "; logind=不可读取"
    return detail


async def run(argv: list[str], timeout: float = 8, limit: int = 8 * 1024 * 1024) -> Output:
    current_user()
    caller = pwd.getpwuid(os.getuid())
    # Credentials are never changed. Mount's explicit as-user is a UDisks option,
    # not an environment variable or a fake login session.
    env = {"PATH": "/usr/bin:/bin", "HOME": caller.pw_dir, "USER": caller.pw_name, "LOGNAME": caller.pw_name,
           "LC_ALL": "C", "SYSTEMD_COLORS": "0"}
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=env, cwd="/",
        )
    except FileNotFoundError as exc:
        raise ReadFailure("missing_command", f"未安装系统命令：{argv[0]}") from exc
    except PermissionError as exc:
        raise ReadFailure("permission_denied", f"当前用户没有执行 {argv[0]} 的权限；不会尝试提权") from exc

    async def read(stream, cap):
        data = bytearray()
        while True:
            chunk = await stream.read(16384)
            if not chunk:
                return data.decode("utf-8", errors="replace")
            data.extend(chunk)
            if len(data) > cap:
                raise ReadFailure("output_limit", f"{argv[0]} 输出超过安全上限，请缩短日志时间范围")

    tasks = [asyncio.create_task(read(proc.stdout, limit)),
             asyncio.create_task(read(proc.stderr, 65536))]
    async def collect():
        stdout, stderr = await asyncio.gather(*tasks)
        await proc.wait()
        return Output(proc.returncode, stdout, stderr)
    try:
        return await asyncio.wait_for(collect(), timeout=timeout)
    except (TimeoutError, asyncio.TimeoutError) as exc:
        raise ReadFailure("timeout", f"{argv[0]} 读取超时") from exc
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await proc.wait()


def require_success(output: Output, command: str) -> str:
    # journalctl may exit successfully while silently filtering inaccessible journals.
    if any(word in output.stderr.lower() for word in (
        "permission denied", "not seeing messages", "insufficient permissions", "access denied"
    )):
        raise ReadFailure("permission_denied", f"没有完整读取 {command} 的权限")
    if output.code:
        raise ReadFailure("read_failed", f"{command} 读取失败：{output.stderr.strip()[:400]}")
    return output.stdout
