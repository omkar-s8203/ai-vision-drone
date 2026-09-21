"""Wrapper around Raspberry Pi/Sony's `imx500-converter` toolchain, for
deploying a custom-trained model to the Raspberry Pi AI Camera (docs plan
M2) - only needed if a required object class isn't already covered by the
stock COCO model this project ships with (see hardware.yaml's own comment
on `imx500_model_path`).

**NOT independently verified against the real `imxconv-tf`/`imxconv-pt`
CLI.** Installing `imx500-converter` and running the real tool needs a
specific Python 3.9-3.11 x86_64 Linux environment (per Raspberry Pi's own
documented install: `pip install imx500-converter[pt]` for a PyTorch/ONNX
model, `imx500-converter[tf]` for TensorFlow/Keras), which isn't available
on this dev machine to check the tool's own `--help` output against. The
`-i`/`-o` flags below match every published Raspberry Pi/Sony IMX500
conversion example, but run `imxconv-tf --help` / `imxconv-pt --help`
yourself once it's installed and adjust CONVERTER_ARGS if they don't
match, before trusting this against a real model - the same "verify
against real behavior before trusting it" discipline the rest of this
project's tooling already follows (see tools/README.md).

Usage:

    python tools/imx500_convert.py my_model.onnx --out imx500_converted/
    python tools/imx500_convert.py my_saved_model_dir/ --out imx500_converted/

Picks `imxconv-pt` for a `.onnx` file or `imxconv-tf` for a `.h5`/`.pb`/
`.keras` file or a SavedModel directory, based on Raspberry Pi's own
documented framework split. Prints the resulting `.rpk` path - point
`companion/config/hardware.yaml`'s `camera.imx500_model_path` at it.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

TF_EXTENSIONS = {".h5", ".pb", ".keras"}
PT_EXTENSIONS = {".onnx"}

# Adjust here if a real `--help` run shows different flag names.
CONVERTER_ARGS = ["-i", "{model}", "-o", "{output_dir}"]


def pick_converter(model_path: Path) -> str:
    if model_path.is_dir() or model_path.suffix in TF_EXTENSIONS:
        return "imxconv-tf"
    if model_path.suffix in PT_EXTENSIONS:
        return "imxconv-pt"
    raise ValueError(
        f"Can't tell which imx500-converter tool {model_path} needs "
        f"(recognized: {sorted(TF_EXTENSIONS)} for imxconv-tf, {sorted(PT_EXTENSIONS)} for imxconv-pt, "
        "or a SavedModel directory for imxconv-tf)"
    )


def convert(model_path: Path, output_dir: Path) -> Path:
    converter = pick_converter(model_path)
    if shutil.which(converter) is None:
        framework_extra = "tf" if converter == "imxconv-tf" else "pt"
        raise RuntimeError(
            f"'{converter}' not found on PATH - install it first: "
            f"pip install 'imx500-converter[{framework_extra}]' (see Raspberry Pi's "
            "official IMX500 documentation for the current package name/install steps)"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    args = [arg.format(model=str(model_path), output_dir=str(output_dir)) for arg in CONVERTER_ARGS]
    subprocess.run([converter, *args], check=True)

    rpk_files = sorted(output_dir.glob("*.rpk"))
    if not rpk_files:
        raise RuntimeError(
            f"{converter} exited successfully but produced no .rpk file in {output_dir} - "
            "check its own console output above for what it actually wrote"
        )
    return rpk_files[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("model", type=Path, help="path to the trained model (.onnx, .h5, .pb, .keras, or a SavedModel dir)")
    parser.add_argument("--out", type=Path, default=Path("imx500_converted"), help="output directory for the converted .rpk")
    args = parser.parse_args()

    try:
        rpk = convert(args.model, args.out)
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Conversion failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Converted model: {rpk}")
    print("Point companion/config/hardware.yaml's camera.imx500_model_path at this file, "
          "then re-run tools/benchmark_detection.py and tools/detection_regression.py "
          "to confirm the new model still meets M2's own acceptance criteria.")


if __name__ == "__main__":
    main()
