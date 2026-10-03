import pytest

from monovrtrack.config import load_config


def test_paths_resolve_against_configuration(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("model:\n  upstream_dir: upstream\n", encoding="utf-8")
    config = load_config(path)
    assert config.model.upstream_dir == str(tmp_path / "upstream")


@pytest.mark.parametrize("text", ["tracking:\n  min_confidence: 2\n", "target_fps: .nan\n",
                                 "unexpected: true\n", "camera:\n  width: -1\n",
                                 "tracking:\n  smoothing: maybe\n", "model:\n  device: cpu\n"])
def test_invalid_config(tmp_path, text):
    path = tmp_path / "bad.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)


@pytest.mark.parametrize("text", ["camera: [", "[]", "false", "0", "model: {device: null}",
                                 "model: {upstream_dir: null}", "model: {device: 3}",
                                 "model: {checkpoint_path: []}", "model: {detector_model_path: 3}"])
def test_bad_yaml_and_model_types_report_value_error(tmp_path, text):
    path = tmp_path / "invalid.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)
