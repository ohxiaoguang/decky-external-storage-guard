"""Real credential drop smoke test uses Python only, never a storage command."""
import asyncio
import json
import os
import pwd
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from storage_guard.commands import DesktopUser, ReadFailure, desktop_user, run


class DesktopIdentityTests(unittest.TestCase):
    def setUp(self):
        self.account = SimpleNamespace(pw_name="player", pw_uid=1002, pw_gid=1003, pw_dir="/home/player")

    def context(self):
        return patch.dict(os.environ, {"DECKY_USER": "player", "DECKY_USER_HOME": "/home/player", "USER": "root", "HOME": "/root"})

    def test_decky_host_identity_uses_passwd_and_groups_not_effective_root(self):
        with self.context(), patch("storage_guard.commands.pwd.getpwnam", return_value=self.account), patch(
                "storage_guard.commands.pwd.getpwuid", return_value=self.account), patch(
                "storage_guard.commands.os.getgrouplist", return_value=[1003, 10, 1003]):
            self.assertEqual(desktop_user(), DesktopUser("player", 1002, 1003, "/home/player", (10, 1003)))

    def test_missing_root_or_mismatched_identity_fails_closed(self):
        for change in ({"DECKY_USER": ""}, {"DECKY_USER_HOME": ""}, {"DECKY_USER_HOME": "/root"}, {"DECKY_USER_HOME": "relative"}):
            with self.context(), patch.dict(os.environ, change), patch("storage_guard.commands.pwd.getpwnam", return_value=self.account), self.assertRaises(ReadFailure):
                desktop_user()
        for changes in ({"pw_uid": 0}, {"pw_gid": 0}, {"pw_name": "other"}):
            account = SimpleNamespace(**{**vars(self.account), **changes})
            with self.context(), patch("storage_guard.commands.pwd.getpwnam", return_value=account), self.assertRaises(ReadFailure):
                desktop_user()
        for lookup in ("getpwnam", "getpwuid"):
            with self.context(), patch("storage_guard.commands.pwd.getpwnam", return_value=self.account), patch(
                    f"storage_guard.commands.pwd.{lookup}", side_effect=KeyError("gone")), self.assertRaises(ReadFailure):
                desktop_user()
        with self.context(), patch("storage_guard.commands.pwd.getpwnam", return_value=self.account), patch(
                "storage_guard.commands.pwd.getpwuid", return_value=SimpleNamespace(pw_name="different")), self.assertRaises(ReadFailure):
            desktop_user()


class UserSubprocessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = DesktopUser("player", 1002, 1003, "/home/player", (10, 1003))

    async def test_root_child_spawn_has_numeric_credentials_clean_environment_and_safe_cwd(self):
        proc = SimpleNamespace(returncode=0, stdout=asyncio.StreamReader(), stderr=asyncio.StreamReader(), wait=AsyncMock())
        proc.stdout.feed_eof(); proc.stderr.feed_eof()
        with patch("storage_guard.commands.os.geteuid", return_value=0), patch.dict(os.environ, {
                "HOME": "/root", "USER": "root", "XDG_RUNTIME_DIR": "/run/user/0", "DBUS_SYSTEM_BUS_ADDRESS": "wrong-bus",
                "LD_PRELOAD": "root-only-library"}), patch("storage_guard.commands.asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as spawn:
            await run(["udisksctl", "mount", "-b", "/dev/test1"], user=self.user)
        args = spawn.call_args.kwargs
        self.assertEqual(args["user"], 1002)
        self.assertEqual(args["group"], 1003)
        self.assertEqual(args["extra_groups"], [10, 1003])
        self.assertEqual(args["cwd"], "/")
        self.assertEqual(args["env"]["HOME"], "/home/player")
        self.assertEqual(args["env"]["USER"], "player")
        self.assertEqual(args["env"]["LOGNAME"], "player")
        self.assertEqual(args["env"]["PATH"], "/usr/bin:/bin")
        for key in ("XDG_RUNTIME_DIR", "DBUS_SYSTEM_BUS_ADDRESS", "LD_PRELOAD"):
            self.assertNotIn(key, args["env"])
        self.assertNotIn("preexec_fn", args)

    async def test_credential_switch_failure_never_retries_as_root(self):
        with patch("storage_guard.commands.os.geteuid", return_value=0), patch(
                "storage_guard.commands.asyncio.create_subprocess_exec", AsyncMock(side_effect=PermissionError("setuid denied"))) as spawn:
            with self.assertRaises(ReadFailure) as caught:
                await run(["udisksctl", "mount"], user=self.user)
            self.assertEqual(caught.exception.status, "permission_denied")
            self.assertEqual(spawn.call_count, 1)
        with patch("storage_guard.commands.asyncio.create_subprocess_exec", AsyncMock()) as spawn:
            with self.assertRaises(ReadFailure):
                await run(["udisksctl", "mount"], user=DesktopUser("root", 0, 0, "/root", (0,)))
            spawn.assert_not_called()

    async def test_wrong_nonroot_process_cannot_pretend_to_switch_users(self):
        with patch("storage_guard.commands.os.geteuid", return_value=2000), patch(
                "storage_guard.commands.os.getresuid", return_value=(2000,) * 3), patch(
                "storage_guard.commands.asyncio.create_subprocess_exec", AsyncMock()) as spawn:
            with self.assertRaises(ReadFailure):
                await run(["udisksctl", "mount"], user=self.user)
            spawn.assert_not_called()

    async def test_actual_child_credentials_are_not_just_home_environment_changes(self):
        before_uid, before_gid, before_groups = os.getresuid(), os.getresgid(), os.getgroups()
        account = pwd.getpwnam("nobody") if os.geteuid() == 0 else pwd.getpwuid(os.geteuid())
        groups = os.getgrouplist(account.pw_name, account.pw_gid) if os.geteuid() == 0 else os.getgroups()
        user = DesktopUser(account.pw_name, account.pw_uid, account.pw_gid, account.pw_dir,
                           tuple(sorted(set(groups) | {account.pw_gid})))
        output = await run([sys.executable, "-c", "import json,os; print(json.dumps([os.getresuid(),os.getresgid(),os.getgroups(),os.environ['HOME']]))"], user=user)
        self.assertEqual(output.code, 0, output.stderr)
        uid, gid, groups, home = json.loads(output.stdout)
        self.assertEqual(uid, [user.uid] * 3)
        self.assertEqual(gid, [user.gid] * 3)
        self.assertEqual(set(groups) | {user.gid}, set(user.groups))
        self.assertEqual(home, user.home)
        self.assertEqual((os.getresuid(), os.getresgid(), os.getgroups()), (before_uid, before_gid, before_groups))
