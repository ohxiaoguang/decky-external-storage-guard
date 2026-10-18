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


@dataclass(frozen=True)
class DesktopUser:
    name: str
    uid: int
    gid: int
    home: str
    groups: tuple[int, ...]


def desktop_user() -> DesktopUser:
    """Decky supplies the host user separately from its root plugin identity."""
    try:
        name, home = os.environ.get("DECKY_USER", ""), os.environ.get("DECKY_USER_HOME", "")
        if not name or not home or not Path(home).is_absolute():
            raise ValueError("missing Decky host user")
        account = pwd.getpwnam(name)
        if (account.pw_name != name or account.pw_uid <= 0 or account.pw_gid <= 0 or
                account.pw_dir != home or home in ("/", "/root") or
                pwd.getpwuid(account.pw_uid).pw_name != name):
            raise ValueError("untrusted Decky host user")
        groups = tuple(sorted(set(os.getgrouplist(name, account.pw_gid))))
        if account.pw_gid not in groups or any(not isinstance(g, int) or g < 0 for g in groups):
            raise ValueError("invalid user groups")
        return DesktopUser(name, account.pw_uid, account.pw_gid, home, groups)
    except (KeyError, ValueError, OSError) as exc:
        raise ReadFailure("unsupported_permissions", "无法确认 Decky 桌面用户身份，已停止挂载；不会回退为 root") from exc


async def run(argv: list[str], timeout: float = 8, limit: int = 8 * 1024 * 1024,
              user: DesktopUser | None = None) -> Output:
    options = {}
    env = {**os.environ, "LC_ALL": "C", "SYSTEMD_COLORS": "0"}
    if user is not None:
        if user.uid <= 0 or user.gid <= 0:
            raise ReadFailure("permission_denied", "禁止以 root 身份执行桌面用户挂载")
        # Popen performs setgroups/setregid/setreuid in the child before exec.
        # Do not change credentials of the long-lived root plugin or use preexec_fn.
        options = {"user": user.uid, "group": user.gid, "extra_groups": list(user.groups), "cwd": "/"}
        if os.geteuid() != 0:
            if (os.getresuid() != (user.uid,) * 3 or os.getresgid() != (user.gid,) * 3 or
                    set(os.getgroups()) | {user.gid} != set(user.groups)):
                raise ReadFailure("permission_denied", "当前进程无法切换为已确认的桌面用户，已停止挂载")
            options = {"cwd": "/"}  # Already that exact user; unprivileged setgroups would fail.
        env = {"PATH": "/usr/bin:/bin", "HOME": user.home, "USER": user.name, "LOGNAME": user.name,
               "LC_ALL": "C", "SYSTEMD_COLORS": "0"}
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=env, **options,
        )
    except FileNotFoundError as exc:
        raise ReadFailure("missing_command", f"未安装系统命令：{argv[0]}") from exc
    except PermissionError as exc:
        message = f"无法以桌面用户身份执行 {argv[0]}：权限不足，已停止且不会回退为 root" if user else f"没有执行 {argv[0]} 的权限"
        raise ReadFailure("permission_denied", message) from exc

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
