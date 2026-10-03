import json

from monovrtrack.cli import main
from monovrtrack.tracking.calibration import Calibration


def test_demo_record_replay_and_scaled_calibration(tmp_path, capsys):
    raw = tmp_path / "raw.jsonl"
    poses = tmp_path / "poses.jsonl"
    assert main(["demo", "--frames", "3", "--rate", "0", "--no-udp",
                 "--record", str(raw), "--output", str(poses)]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["valid_frames"] == 3
    assert stats["processing_fps"] > 0
    assert len(poses.read_text().splitlines()) == 3
    assert main(["replay", str(raw), "--rate", "0", "--no-udp"]) == 0
    assert json.loads(capsys.readouterr().out)["valid_frames"] == 3
    saved = tmp_path / "calibration.json"
    assert main(["calibrate", "--demo", "--scale", "1.2", "--origin", "1", "0", "-2",
                 "--save", str(saved)]) == 0
    calibration = Calibration.load(saved)
    assert calibration.scale == 1.2
    assert calibration.translation == (1.0, 0.0, -2.0)


def test_camera_missing_model_reports_actionable_error(capsys):
    assert main(["run", "--frames", "1"]) == 2
    assert "setup_models.py" in capsys.readouterr().err


def test_broken_configuration_reports_no_traceback(tmp_path, capsys):
    config = tmp_path / "broken.yaml"
    config.write_text("camera: [", encoding="utf-8")
    assert main(["demo", "--config", str(config)]) == 2
    assert "Invalid YAML" in capsys.readouterr().err


def test_broken_calibration_reports_no_traceback(tmp_path, capsys):
    calibration = tmp_path / "broken.json"
    calibration.write_text("[]", encoding="utf-8")
    assert main(["demo", "--calibration", str(calibration)]) == 2
    assert "Calibration must be a JSON object" in capsys.readouterr().err
