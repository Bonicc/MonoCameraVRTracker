from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


script = Path(__file__).resolve().parents[1] / "scripts" / "setup_models.py"
spec = importlib.util.spec_from_file_location("setup_models_under_test", script)
setup_models = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup_models)


class ModelSourceSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_unrelated_existing_directory_is_not_overwritten(self):
        destination = self.root / "existing"
        destination.mkdir()
        existing_file = destination / "user-file.txt"
        existing_file.write_text("keep me", encoding="utf-8")
        with patch.object(setup_models.subprocess, "run") as command:
            with self.assertRaisesRegex(RuntimeError, "not a Git clone"):
                setup_models.setup_source(destination)
        command.assert_not_called()
        self.assertEqual(existing_file.read_text(encoding="utf-8"), "keep me")

    def test_existing_wrong_revision_is_not_reset(self):
        destination = self.root / "existing"
        (destination / ".git").mkdir(parents=True)
        with patch.object(setup_models.subprocess, "check_output", side_effect=[
            "another-revision\n", setup_models.UPSTREAM_URL + "\n", "",
        ]), patch.object(setup_models.subprocess, "run") as command:
            with self.assertRaisesRegex(RuntimeError, "left untouched"):
                setup_models.setup_source(destination)
        command.assert_not_called()

    def test_modified_source_at_correct_revision_is_not_accepted_as_pinned(self):
        destination = self.root / "existing"
        (destination / ".git").mkdir(parents=True)
        with patch.object(setup_models.subprocess, "check_output", side_effect=[
            setup_models.UPSTREAM_REVISION + "\n", setup_models.UPSTREAM_URL + "\n",
            " M sam_3d_body/build_models.py\n",
        ]), patch.object(setup_models.subprocess, "run") as command:
            with self.assertRaisesRegex(RuntimeError, "local tracked modifications"):
                setup_models.setup_source(destination)
        command.assert_not_called()

    def test_matching_source_does_not_clone_or_checkout_again(self):
        destination = self.root / "existing"
        (destination / ".git").mkdir(parents=True)
        with patch.object(setup_models.subprocess, "check_output", side_effect=[
            setup_models.UPSTREAM_REVISION + "\n", setup_models.UPSTREAM_URL + "\n", "",
        ]), patch.object(setup_models.subprocess, "run") as command:
            setup_models.setup_source(destination)
        command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
