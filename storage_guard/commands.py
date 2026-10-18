"""Bounded, cancellable subprocesses. Commands and arguments are backend-owned."""
import asyncio
import os
from dataclasses import dataclass


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


async def run(argv: list[str], timeout: float = 8, limit: int = 8 * 1024 * 1024) -> Output:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "LC_ALL": "C", "SYSTEMD_COLORS": "0"},
        )
    except FileNotFoundError as exc:
        raise ReadFailure("missing_command", f"未安装系统命令：{argv[0]}") from exc
    except PermissionError as exc:
        raise ReadFailure("permission_denied", f"没有执行 {argv[0]} 的权限") from exc

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
