"""Native API contract tests, not a simulated grant of polkit authorization."""
import json
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from storage_guard import udisks
from storage_guard.commands import Output, ReadFailure
from storage_guard.remount import safe_mount_target
from test_remount import managed_device


def reply(signature, data):
    return Output(0, json.dumps({"type": signature, "data": data}), "")


class NativeUDisksTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.part = managed_device()["partitions"][1]
        # Shape obtained from a real busctl GetAll on a private test D-Bus.
        self.props = {"DeviceNumber": {"type": "t", "data": os.makedev(179, 1)},
                      "IdUUID": {"type": "s", "data": self.part["uuid"]},
                      "IdType": {"type": "s", "data": "ext4"},
                      "Configuration": {"type": "a(sa{sv})", "data": []}}

    async def prepare(self, version="2.10.0", action="mount", readonly=False):
        outputs = [reply("s", version), reply("a{sv}", [self.props])]
        with patch("storage_guard.udisks.os.getresuid", return_value=(0, 0, 0)), patch(
                "storage_guard.udisks.run", AsyncMock(side_effect=outputs)) as command:
            path = await udisks.prepare(self.part, action, safe_mount_target, readonly)
        return path, command

    async def test_native_metadata_checked_before_any_state_changing_call(self):
        for action in ("mount", "unmount"):
            path, command = await self.prepare(action=action)
            self.assertEqual(path, "/org/freedesktop/UDisks2/block_devices/mmcblk0p1")
            self.assertTrue(all("Mount" not in c.args[0] and "Unmount" not in c.args[0] for c in command.call_args_list))
            self.assertEqual(command.call_count, 2)

    async def test_old_unknown_daemon_never_reaches_mount_or_metadata_lookup(self):
        for version in ("2.9.4", "2.8.4", "unknown", "", None):
            with patch("storage_guard.udisks.os.getresuid", return_value=(0, 0, 0)), patch(
                    "storage_guard.udisks.run", AsyncMock(return_value=reply("s", version))) as command:
                with self.assertRaises(ReadFailure) as caught:
                    await udisks.prepare(self.part, "mount", safe_mount_target)
                self.assertEqual(caught.exception.status, "unsupported")
                self.assertEqual(command.call_count, 1)
                self.assertIn("get-property", command.call_args.args[0])
        await self.prepare(version="2.11.0")

    async def test_nonroot_background_process_refuses_without_terminal_or_authentication_retry(self):
        with patch("storage_guard.udisks.os.getresuid", return_value=(1000,) * 3), patch(
                "storage_guard.udisks.run", AsyncMock()) as command:
            with self.assertRaises(ReadFailure) as caught:
                await udisks.prepare(self.part, "mount", safe_mount_target)
            self.assertEqual(caught.exception.status, "permission_denied")
            command.assert_not_called()

    async def test_wrong_device_number_uuid_or_filesystem_fails_closed(self):
        original = deepcopy(self.props)
        for key, value in (("DeviceNumber", 0), ("IdUUID", "another-card"), ("IdType", "swap")):
            self.props = deepcopy(original)
            self.props[key]["data"] = value
            with self.assertRaises(ReadFailure) as caught:
                await self.prepare()
            self.assertEqual(caught.exception.status, "stale_target")

    def fstab(self, directory, options="defaults"):
        self.props["Configuration"]["data"] = [["fstab", {
            "dir": {"type": "ay", "data": list(directory.encode() + b"\0")},
            "opts": {"type": "ay", "data": list(options.encode() + b"\0")}}]]

    async def test_unsafe_fstab_root_system_and_plugin_destinations_prevent_mount(self):
        for directory in ("/run/media/root/SN512", "/root", "/", "/home", "/mnt/../root"):
            self.fstab(directory)
            with self.assertRaises(ReadFailure):
                await self.prepare()
        self.fstab("/mnt/games")
        with patch.dict(os.environ, {"DECKY_PLUGIN_DIR": "/mnt/games/homebrew/plugins/guard"}), self.assertRaises(ReadFailure):
            await self.prepare()

    async def test_custom_user_directory_allowed_but_fstab_cannot_ignore_readonly(self):
        self.fstab("/mnt/My Games", "defaults")
        await self.prepare()
        with self.assertRaises(ReadFailure):
            await self.prepare(readonly=True)
        self.fstab("/mnt/My Games", "ro,nosuid")
        await self.prepare(readonly=True)

    def test_symlink_target_cannot_alias_system_or_root_directory(self):
        with patch("storage_guard.remount.Path.resolve", return_value=Path("/root")):
            self.assertFalse(safe_mount_target("/mnt/link"))

    def test_no_tty_native_call_has_explicit_user_and_no_force_or_interactive_agent(self):
        user = SimpleNamespace(pw_name="deck")
        args = udisks.action_command(udisks.object_path("mmcblk0p1"), "mount", user, ["ro", "nosuid"])
        self.assertEqual(args[0], "busctl")
        self.assertIn("--allow-interactive-authorization=no", args)
        self.assertEqual(args[-10:], ["3", "auth.no_user_interaction", "b", "true", "as-user", "s", "deck", "options", "s", "ro,nosuid"])
        for forbidden in ("udisksctl", "sudo", "pkexec", "force", "rw", "root"):
            self.assertNotIn(forbidden, args)
        unmount = udisks.action_command(udisks.object_path("mmcblk0p1"), "unmount", user, [])
        self.assertEqual(unmount[-5:], ["a{sv}", "1", "auth.no_user_interaction", "b", "true"])

    def test_native_path_encoding_and_mount_reply_shape(self):
        self.assertEqual(udisks.object_path("dm_1-2"), "/org/freedesktop/UDisks2/block_devices/dm_5f1_2d2")
        self.assertEqual(udisks.mounted_path(reply("s", ["/run/media/deck/SN512"]).stdout), "/run/media/deck/SN512")
        for output in ("Mounted /dev/mmcblk0p1", reply("s", "/root").stdout, reply("as", ["/mnt/card"]).stdout):
            with self.assertRaises(ReadFailure): udisks.mounted_path(output)
