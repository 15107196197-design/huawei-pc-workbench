"""Offline deployment tests: no settings, credentials, providers or model calls."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch


DIRECTORY = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("modelscope_entrypoint", DIRECTORY / "entrypoint.py")
entrypoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entrypoint)
health_spec = importlib.util.spec_from_file_location("modelscope_healthcheck", DIRECTORY / "healthcheck.py")
healthcheck = importlib.util.module_from_spec(health_spec)
health_spec.loader.exec_module(healthcheck)


class PersistentDataTests(unittest.TestCase):
    def test_data_survives_reinitialization_without_replacing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / "studio"
            self.assertEqual(entrypoint.prepare_data(target, base), target.resolve())
            (target / "persisted.txt").write_text("kept", encoding="utf-8")
            self.assertEqual(entrypoint.prepare_data(target, base), target.resolve())
            self.assertEqual((target / "persisted.txt").read_text(), "kept")
            entrypoint.check_writable(target)
            self.assertTrue((target / "media").is_dir())
            self.assertTrue((target / "generated").is_dir())
            self.assertEqual(list(target.glob(".startup-write-check-*")), [])

    def test_mount_root_and_outside_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            for target in [base, base.parent / "outside"]:
                with self.assertRaisesRegex(RuntimeError, "dedicated subdirectory"):
                    entrypoint.prepare_data(target, base)

    def test_relative_directory_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "absolute"):
            entrypoint.prepare_data(Path("data"))

    def test_symlinked_child_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            real = base / "actual"
            real.mkdir()
            link = base / "linked"
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "symlinked descendants"):
                entrypoint.prepare_data(link, base)

    def test_symlinked_media_is_not_followed(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / "studio"
            target.mkdir()
            (target / "media").symlink_to(base, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "symbolic links"):
                entrypoint.prepare_data(target, base)

    def test_unwritable_directory_stops_startup(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(entrypoint.os, "open", side_effect=PermissionError("denied")):
                with self.assertRaisesRegex(RuntimeError, "UID/GID 10001:10001"):
                    entrypoint.check_writable(Path(temporary))

    def test_root_changes_only_three_directory_owners_without_recursion(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / "studio"
            with patch.object(entrypoint.os, "geteuid", return_value=0), patch.object(entrypoint.os, "chown") as chown:
                entrypoint.prepare_data(target, base)
            target = target.resolve()
            self.assertEqual(chown.call_args_list, [
                call(target, 10001, 10001), call(target / "media", 10001, 10001),
                call(target / "generated", 10001, 10001),
            ])


class PrivilegeDropTests(unittest.TestCase):
    def test_root_clears_groups_before_dropping_gid_and_uid(self):
        sequence = []
        with patch.object(entrypoint.os, "geteuid", side_effect=[0, 10001]), patch.object(entrypoint.os, "getegid", return_value=10001), \
             patch.object(entrypoint.os, "setgroups", side_effect=lambda value: sequence.append(("groups", value))), \
             patch.object(entrypoint.os, "setgid", side_effect=lambda value: sequence.append(("gid", value))), \
             patch.object(entrypoint.os, "setuid", side_effect=lambda value: sequence.append(("uid", value))):
            entrypoint.drop_privileges()
        self.assertEqual(sequence, [("groups", []), ("gid", 10001), ("uid", 10001)])

    def test_platform_service_uid_needs_no_root_operations(self):
        with patch.object(entrypoint.os, "geteuid", return_value=10001), patch.object(entrypoint.os, "getegid", return_value=10001), \
             patch.object(entrypoint.os, "setgroups") as groups:
            entrypoint.drop_privileges()
            groups.assert_not_called()

    def test_unexpected_uid_is_rejected(self):
        with patch.object(entrypoint.os, "geteuid", return_value=12345):
            with self.assertRaisesRegex(RuntimeError, "10001:10001"):
                entrypoint.drop_privileges()


class HealthCheckTests(unittest.TestCase):
    def check_with_response(self, status, body):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.status = status
        response.read.return_value = body
        response.__enter__.return_value = response
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(healthcheck, "build_opener", return_value=opener):
            healthcheck.main()
        opener.open.assert_called_once_with("http://127.0.0.1:7860/healthz", timeout=4)

    def test_json_health_body_matches_core_application(self):
        self.check_with_response(200, b'{"status":"ok"}')

    def test_nonhealthy_status_is_rejected(self):
        with self.assertRaises(SystemExit):
            self.check_with_response(503, b'{"status":"error"}')

    def test_wrong_success_body_is_rejected(self):
        with self.assertRaises(SystemExit):
            self.check_with_response(200, b'{"status":"waiting"}')


if __name__ == "__main__":
    unittest.main()
