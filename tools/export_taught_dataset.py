"""Packages the photos collected by Teach mode into a standard YOLO training set.

Teach mode (companion/learning) saves, per taught object, `images/*.jpg` plus a
YOLO label file per image under `companion/datasets/<name>/`. This tool merges
every taught object into one dataset a trainer can read:

    python tools/export_taught_dataset.py --datasets companion/datasets --out export/taught_v1

Output:

    export/taught_v1/
        data.yaml                  # class names + train/val paths (Ultralytics format)
        images/train, images/val
        labels/train, labels/val

Train/val split is CHRONOLOGICAL per object (the last `--val-fraction` of each
object's photos become validation), not random: consecutive frames of the same
moving object are near-duplicates, and a random split would put almost-identical
images in both sets and make the model look far better than it is.

It only packages data - it does not train anything. See docs/teach-and-train.md
for the training and IMX500 conversion steps, and for why a model trained ONLY
on taught objects will forget the everyday classes (people, cars) unless you
merge in a general dataset.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

MIN_RECOMMENDED_PER_OBJECT = 100


def _sample_index(path: Path) -> int:
    match = re.search(r"_(\d+)$", path.stem)
    return int(match.group(1)) if match else 0


def export_dataset(datasets: Path, out: Path, val_fraction: float = 0.2) -> dict:
    """Returns {"classes": [...], "counts": {name: {"train": n, "val": n}}, "skipped": n,
    "warnings": [...]}. Raises ValueError if there is nothing to export."""
    if not 0.0 <= val_fraction < 1.0:
        raise ValueError("val_fraction must be in [0, 1)")
    registry_path = datasets / "taught_objects.json"
    if not registry_path.exists():
        raise ValueError(f"No taught_objects.json in {datasets} - nothing has been taught yet")
    objects = sorted(json.loads(registry_path.read_text(encoding="utf-8"))["objects"], key=lambda o: o["class_id"])

    classes: list[str] = []
    counts: dict[str, dict[str, int]] = {}
    warnings: list[str] = []
    skipped = 0
    for split in ("train", "val"):
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)

    for obj in objects:
        name = obj["name"]
        image_dir = datasets / name / "images"
        label_dir = datasets / name / "labels"
        images = sorted(image_dir.glob("*.jpg"), key=_sample_index) if image_dir.exists() else []
        usable = []
        for image in images:
            label = label_dir / (image.stem + ".txt")
            if label.exists():
                usable.append((image, label))
            else:
                skipped += 1  # an image without a label would train the model that the object is absent
        if not usable:
            warnings.append(f"{name}: no labelled images - left out")
            continue
        class_index = len(classes)
        classes.append(name)
        n_val = int(round(len(usable) * val_fraction))
        if val_fraction > 0 and len(usable) >= 2:
            n_val = max(1, n_val)
        n_train = len(usable) - n_val
        counts[name] = {"train": n_train, "val": n_val}
        if len(usable) < MIN_RECOMMENDED_PER_OBJECT:
            warnings.append(
                f"{name}: only {len(usable)} photos - aim for {MIN_RECOMMENDED_PER_OBJECT}+ across "
                "different angles, distances, lighting and backgrounds"
            )
        for position, (image, label) in enumerate(usable):
            split = "train" if position < n_train else "val"
            shutil.copy2(image, out / "images" / split / image.name)
            parts = label.read_text(encoding="utf-8").split()
            (out / "labels" / split / label.name).write_text(
                " ".join([str(class_index)] + parts[1:]) + "\n", encoding="utf-8"
            )

    if not classes:
        raise ValueError("No labelled photos found for any taught object")

    names = "\n".join(f"  {i}: {name}" for i, name in enumerate(classes))
    (out / "data.yaml").write_text(
        f"path: {out.resolve().as_posix()}\ntrain: images/train\nval: images/val\nnames:\n{names}\n",
        encoding="utf-8",
    )
    return {"classes": classes, "counts": counts, "skipped": skipped, "warnings": warnings}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--datasets", type=Path, default=Path("companion/datasets"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--val-fraction", type=float, default=0.2)
    args = parser.parse_args(argv)
    try:
        summary = export_dataset(args.datasets, args.out, args.val_fraction)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for name in summary["classes"]:
        c = summary["counts"][name]
        print(f"{name}: {c['train']} train / {c['val']} val")
    for warning in summary["warnings"]:
        print(f"warning: {warning}")
    if summary["skipped"]:
        print(f"skipped {summary['skipped']} image(s) with no label file")
    print(f"wrote {args.out / 'data.yaml'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
