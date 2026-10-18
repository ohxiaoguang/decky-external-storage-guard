"""Test harness: verify imports and unchanged process credentials; no storage operations."""
import os
from pathlib import Path
import pwd
import subprocess
import sys

WORKER = r'''
import asyncio, errno, json, os, sys
from unittest.mock import AsyncMock, patch
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
from main import Plugin
from storage_guard.commands import current_user, run, ReadFailure
async def check():
    user = current_user()
    assert user.pw_uid > 0 and user.pw_gid > 0
    assert os.getuid() in (0, user.pw_uid)
    assert not os.isatty(0), 'backend smoke must run without a controlling input terminal'
    try:
        fd = os.open('/dev/tty', os.O_RDONLY | os.O_NOCTTY)
    except OSError as error:
        assert error.errno in (errno.ENXIO, errno.ENODEV, errno.ENOENT), error
    else:
        os.close(fd)
        raise AssertionError('unexpected controlling terminal')
    before = [list(os.getresuid()), list(os.getresgid()), os.getgroups(), os.environ['HOME']]
    output = await run([sys.executable, '-c', 'import os,json; print(json.dumps([list(os.getresuid()),list(os.getresgid()),os.getgroups(),os.environ["HOME"]]))'])
    assert output.code == 0, output.stderr
    assert json.loads(output.stdout) == before
    plugin = Plugin()
    assert callable(plugin.get_snapshot) and callable(plugin.get_logs)
    assert callable(plugin.mount_partition) and callable(plugin.unmount_partition)
    assert not hasattr(plugin, "remount_partition")
    await plugin._main()
    with patch('storage_guard.service.scan', AsyncMock(return_value=([], [], []))):
        assert (await plugin.get_snapshot())['deviceStatus']['status'] == 'ok'
    with patch('storage_guard.service.read_journal', AsyncMock(side_effect=ReadFailure('permission_denied', 'actual access denied'))):
        assert (await plugin.get_logs())['status'] == 'permission_denied'
    await plugin._unload()
    await plugin._uninstall()
asyncio.run(check())
print('Backend runtime and unchanged subprocess credentials: OK')
'''


def check(plugin):
    account = pwd.getpwnam("nobody") if os.geteuid() == 0 else pwd.getpwuid(os.getuid())
    # No credential switching or fake polkit. Exercise the actual test process;
    # real UDisks authorization remains a SteamOS device verification step.
    env = {**os.environ, "DECKY_USER": account.pw_name, "DECKY_USER_HOME": account.pw_dir,
           "HOME": pwd.getpwuid(os.getuid()).pw_dir, "USER": pwd.getpwuid(os.getuid()).pw_name, "DECKY_PLUGIN_RUNTIME_DIR": "/nonexistent/guard-test-runtime"}
    subprocess.run([sys.executable, "-I", "-c", WORKER, str(Path(plugin).resolve())], env=env, stdin=subprocess.DEVNULL,
                   cwd="/", start_new_session=True, check=True, timeout=10)


if __name__ == "__main__":
    check(sys.argv[1])
