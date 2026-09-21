"""Tests for tools/imx500_convert.py. The real imxconv-tf/imxconv-pt CLI
isn't installed on this dev machine (see the module's own docstring for
why) - shutil.which and subprocess.run are mocked so the wrapper's own
logic (converter selection, error messages, output validation) is testable
without it."""

from unittest.mock import patch

import pytest

from tools.imx500_convert import convert, pick_converter


def test_pick_converter_selects_pt_for_onnx(tmp_path):
    model = tmp_path / "model.onnx"
    model.touch()
    assert pick_converter(model) == "imxconv-pt"


@pytest.mark.parametrize("suffix", [".h5", ".pb", ".keras"])
def test_pick_converter_selects_tf_for_known_extensions(tmp_path, suffix):
    model = tmp_path / f"model{suffix}"
    model.touch()
    assert pick_converter(model) == "imxconv-tf"


def test_pick_converter_selects_tf_for_a_saved_model_directory(tmp_path):
    model_dir = tmp_path / "saved_model"
    model_dir.mkdir()
    assert pick_converter(model_dir) == "imxconv-tf"


def test_pick_converter_rejects_an_unrecognized_extension(tmp_path):
    model = tmp_path / "model.weird"
    model.touch()
    with pytest.raises(ValueError):
        pick_converter(model)


def test_convert_raises_a_clear_error_when_the_tool_is_not_installed(tmp_path):
    model = tmp_path / "model.onnx"
    model.touch()
    with patch("tools.imx500_convert.shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="imxconv-pt"):
            convert(model, tmp_path / "out")


def test_convert_raises_when_the_tool_produces_no_rpk_file(tmp_path):
    model = tmp_path / "model.onnx"
    model.touch()
    out_dir = tmp_path / "out"
    with patch("tools.imx500_convert.shutil.which", return_value="/usr/bin/imxconv-pt"), patch(
        "tools.imx500_convert.subprocess.run"
    ) as mock_run:
        with pytest.raises(RuntimeError, match="no .rpk file"):
            convert(model, out_dir)
    mock_run.assert_called_once()


def test_convert_returns_the_produced_rpk_path(tmp_path):
    model = tmp_path / "model.onnx"
    model.touch()
    out_dir = tmp_path / "out"

    def fake_run(cmd, check):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "network.rpk").touch()

    with patch("tools.imx500_convert.shutil.which", return_value="/usr/bin/imxconv-pt"), patch(
        "tools.imx500_convert.subprocess.run", side_effect=fake_run
    ):
        result = convert(model, out_dir)
    assert result == out_dir / "network.rpk"


def test_convert_passes_the_documented_i_o_flags_to_the_converter(tmp_path):
    model = tmp_path / "model.onnx"
    model.touch()
    out_dir = tmp_path / "out"

    def fake_run(cmd, check):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "network.rpk").touch()

    with patch("tools.imx500_convert.shutil.which", return_value="/usr/bin/imxconv-pt"), patch(
        "tools.imx500_convert.subprocess.run", side_effect=fake_run
    ) as mock_run:
        convert(model, out_dir)
    called_cmd = mock_run.call_args[0][0]
    assert called_cmd[0] == "imxconv-pt"
    assert "-i" in called_cmd and str(model) in called_cmd
    assert "-o" in called_cmd and str(out_dir) in called_cmd
