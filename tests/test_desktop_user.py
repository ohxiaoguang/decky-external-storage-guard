"""Separate the verified desktop account from actual process authorization."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from storage_guard.commands import Output, ReadFailure, authorization_context, current_user, run


class CurrentIdentityTests(unittest.TestCase):
    def setUp(self):
        self.account = SimpleNamespace(pw_name="player", pw_uid=1002, pw_gid=1003, pw_dir="/home/player")
        for name, value in (("getuid", 1002), ("getgid", 1003), ("getresuid", (1002,) * 3), ("getresgid", (1003,) * 3)):
            patcher = patch(f"storage_guard.commands.os.{name}", return_value=value)
            patcher.start(); self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {"DECKY_USER": "player", "DECKY_USER_HOME": "/home/player", "HOME": "/home/player"})
        env.start(); self.addCleanup(env.stop)
        account = patch("storage_guard.commands.pwd.getpwnam", return_value=self.account)
        account.start(); self.addCleanup(account.stop)
        reverse = patch("storage_guard.commands.pwd.getpwuid", return_value=self.account)
        reverse.start(); self.addCleanup(reverse.stop)

    def test_actual_process_uid_selects_passwd_not_environment_username(self):
        self.assertEqual(current_user(), self.account)
        with patch.dict(os.environ, {"DECKY_USER": "other"}), self.assertRaises(ReadFailure):
            current_user()

    def test_missing_or_mismatched_home_and_unknown_account_fail_closed(self):
        for change in ({"DECKY_USER": ""}, {"DECKY_USER_HOME": ""}, {"DECKY_USER_HOME": "/root"}, {"HOME": "/root"}):
            with patch.dict(os.environ, change), self.assertRaises(ReadFailure):
                current_user()
        with patch("storage_guard.commands.pwd.getpwuid", side_effect=KeyError("unknown")), self.assertRaises(ReadFailure):
            current_user()

    def test_mixed_saved_credentials_and_wrong_group_fail_closed(self):
        for name, value in (("getgid", 0), ("getresuid", (1002, 1002, 0)),
                            ("getresgid", (1003, 0, 1003)), ("getgid", 1004)):
            with patch(f"storage_guard.commands.os.{name}", return_value=value), self.assertRaises(ReadFailure):
                current_user()

    def test_root_caller_keeps_verified_nonroot_desktop_identity(self):
        with patch("storage_guard.commands.os.getuid", return_value=0), patch("storage_guard.commands.os.getgid", return_value=0), patch(
                "storage_guard.commands.os.getresuid", return_value=(0,) * 3), patch("storage_guard.commands.os.getresgid", return_value=(0,) * 3), patch.dict(os.environ, {"HOME": "/root"}):
            self.assertEqual(current_user(), self.account)
            with patch("storage_guard.commands.pwd.getpwnam", return_value=SimpleNamespace(pw_name="player", pw_uid=0, pw_gid=0, pw_dir="/root")), self.assertRaises(ReadFailure):
                current_user()


class UserSubprocessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.account = SimpleNamespace(pw_name="player", pw_uid=1002, pw_gid=1003, pw_dir="/home/player")

    async def test_commands_inherit_real_credentials_without_switch_parameters(self):
        proc = SimpleNamespace(returncode=0, stdout=asyncio.StreamReader(), stderr=asyncio.StreamReader(), wait=AsyncMock())
        proc.stdout.feed_eof(); proc.stderr.feed_eof()
        for action in ("mount", "unmount", "journalctl"):
            with patch("storage_guard.commands.current_user", return_value=self.account), patch.dict(os.environ, {
                    "DBUS_SYSTEM_BUS_ADDRESS": "wrong-bus", "LD_PRELOAD": "unrelated-library"}), patch(
                    "storage_guard.commands.asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as spawn:
                await run(["journalctl"] if action == "journalctl" else ["udisksctl", action])
            args = spawn.call_args.kwargs
            for key in ("user", "group", "extra_groups", "preexec_fn"):
                self.assertNotIn(key, args)
            import pwd
            caller = pwd.getpwuid(os.getuid())
            self.assertEqual(args["env"]["HOME"], caller.pw_dir)
            self.assertEqual(args["env"]["USER"], caller.pw_name)
            self.assertEqual(args["cwd"], "/")
            for key in ("DBUS_SYSTEM_BUS_ADDRESS", "LD_PRELOAD"):
                self.assertNotIn(key, args["env"])

    async def test_identity_and_execution_permission_failures_do_not_retry(self):
        with patch("storage_guard.commands.current_user", side_effect=ReadFailure("permission_denied", "untrusted")), patch(
                "storage_guard.commands.asyncio.create_subprocess_exec", AsyncMock()) as spawn:
            with self.assertRaises(ReadFailure): await run(["udisksctl", "mount"])
            spawn.assert_not_called()
        with patch("storage_guard.commands.current_user", return_value=self.account), patch(
                "storage_guard.commands.asyncio.create_subprocess_exec", AsyncMock(side_effect=PermissionError("denied"))) as spawn:
            with self.assertRaises(ReadFailure) as caught: await run(["udisksctl", "mount"])
            self.assertEqual(caught.exception.status, "permission_denied")
            self.assertEqual(spawn.call_count, 1)

    async def test_environment_and_same_uid_do_not_create_logind_session_authorization(self):
        with patch.dict(os.environ, {"USER": "deck", "HOME": "/home/deck", "DBUS_SESSION_BUS_ADDRESS": "session-env-does-not-grant-polkit"}), patch(
                "storage_guard.commands.os.isatty", return_value=False), patch("storage_guard.commands.os.getgroups", return_value=[1000]), patch(
                "storage_guard.commands.run", AsyncMock(return_value=Output(1, "", "No session 'self' known"))) as command:
            detail = await authorization_context()
        self.assertIn("tty=False", detail)
        self.assertIn("groups=1000", detail)
        self.assertIn("无可确认的登录会话", detail)
        self.assertEqual(command.call_args.args[0][:3], ["loginctl", "show-session", "self"])
        with patch("storage_guard.commands.run", AsyncMock(return_value=Output(0, "Id=7\nUser=1000\nActive=yes\nSeat=seat0", ""))):
            self.assertIn("Active=yes, Seat=seat0", await authorization_context())

    async def test_backend_and_subprocess_preserve_real_credentials_without_fake_authorization(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, str(root / "tests/backend-runtime-smoke.py"), str(root)],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Backend runtime and unchanged subprocess credentials: OK", result.stdout)
