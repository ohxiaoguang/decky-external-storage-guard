"""Non-root identity checks; no production credential switching is permitted."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from storage_guard.commands import ReadFailure, current_user, run


class CurrentIdentityTests(unittest.TestCase):
    def setUp(self):
        self.account = SimpleNamespace(pw_name="player", pw_uid=1002, pw_gid=1003, pw_dir="/home/player")
        for name, value in (("getuid", 1002), ("getgid", 1003), ("getresuid", (1002,) * 3), ("getresgid", (1003,) * 3)):
            patcher = patch(f"storage_guard.commands.os.{name}", return_value=value)
            patcher.start(); self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {"DECKY_USER": "player", "DECKY_USER_HOME": "/home/player", "HOME": "/home/player"})
        env.start(); self.addCleanup(env.stop)
        account = patch("storage_guard.commands.pwd.getpwuid", return_value=self.account)
        account.start(); self.addCleanup(account.stop)

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

    def test_root_saved_root_and_mismatched_group_fail_even_with_plausible_environment(self):
        for name, value in (("getuid", 0), ("getgid", 0), ("getresuid", (1002, 1002, 0)),
                            ("getresgid", (1003, 0, 1003)), ("getgid", 1004)):
            with patch(f"storage_guard.commands.os.{name}", return_value=value), self.assertRaises(ReadFailure):
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
            self.assertEqual(args["env"]["HOME"], self.account.pw_dir)
            self.assertEqual(args["env"]["USER"], self.account.pw_name)
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

    async def test_backend_really_runs_as_nonroot_with_inherited_groups_and_readonly_install(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, str(root / "tests/nonroot-backend-smoke.py"), str(root)],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Non-root backend and inherited subprocess credentials: OK", result.stdout)
