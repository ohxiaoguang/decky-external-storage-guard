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
    """Verify the existing non-root process; environment is only a cross-check."""
    try:
        uid, gid = os.getuid(), os.getgid()
        if uid <= 0 or gid <= 0 or os.getresuid() != (uid,) * 3 or os.getresgid() != (gid,) * 3:
            raise ValueError("not an ordinary user process")
        account = pwd.getpwuid(uid)
        if (account.pw_uid != uid or account.pw_gid != gid or not Path(account.pw_dir).is_absolute() or account.pw_dir in ("/", "/root") or
                os.environ.get("DECKY_USER") != account.pw_name or
                os.environ.get("DECKY_USER_HOME") != account.pw_dir or os.environ.get("HOME") != account.pw_dir):
            raise ValueError("process does not match Decky host user")
        return account
    except (KeyError, ValueError, OSError) as exc:
        raise ReadFailure("permission_denied", "无法确认当前普通用户身份；请确认插件已更新并以非 root 模式重新加载") from exc


async def run(argv: list[str], timeout: float = 8, limit: int = 8 * 1024 * 1024) -> Output:
    user = current_user()
    # Keep the process's real UID/GID and actual supplementary groups unchanged.
    env = {"PATH": "/usr/bin:/bin", "HOME": user.pw_dir, "USER": user.pw_name, "LOGNAME": user.pw_name,
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
