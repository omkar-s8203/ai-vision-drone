import json

import pytest

from companion.vision.detector import load_class_names
from tools.export_taught_dataset import export_dataset, main


def _make(root, name, class_id, n, unlabelled=0):
    (root / name / "images").mkdir(parents=True)
    (root / name / "labels").mkdir(parents=True)
    for i in range(n):
        stem = f"{name}_1700000000_{i:05d}"
        (root / name / "images" / f"{stem}.jpg").write_bytes(b"jpeg")
        if i >= n - unlabelled:
            continue
        (root / name / "labels" / f"{stem}.txt").write_text("0 0.5 0.5 0.2 0.3\n")


def _registry(root, entries):
    (root / "taught_objects.json").write_text(json.dumps({"objects": [
        {"name": n, "class_id": c, "real_width_m": None, "real_height_m": None, "created_ts": 0.0} for n, c in entries
    ]}))


def test_exports_a_yolo_dataset_with_remapped_class_ids(tmp_path):
    data = tmp_path / "datasets"
    data.mkdir()
    _make(data, "backpack", 10000, 10)
    _make(data, "truck", 10001, 10)
    _registry(data, [("backpack", 10000), ("truck", 10001)])
    out = tmp_path / "out"

    summary = export_dataset(data, out, val_fraction=0.2)

    assert summary["classes"] == ["backpack", "truck"]
    assert summary["counts"]["backpack"] == {"train": 8, "val": 2}
    yaml_text = (out / "data.yaml").read_text()
    assert "0: backpack" in yaml_text and "1: truck" in yaml_text and "train: images/train" in yaml_text
    truck_labels = list((out / "labels" / "train").glob("truck_*.txt"))
    assert truck_labels and all(p.read_text().split()[0] == "1" for p in truck_labels)   # class 0 -> global 1
    assert all(p.read_text().split()[1:] == ["0.5", "0.5", "0.2", "0.3"] for p in truck_labels)  # box untouched


def test_the_split_is_chronological_so_near_duplicates_do_not_leak(tmp_path):
    data = tmp_path / "datasets"
    data.mkdir()
    _make(data, "backpack", 10000, 10)
    _registry(data, [("backpack", 10000)])
    out = tmp_path / "out"
    export_dataset(data, out, val_fraction=0.2)
    val_indices = sorted(int(p.stem.rsplit("_", 1)[1]) for p in (out / "images" / "val").glob("*.jpg"))
    train_indices = sorted(int(p.stem.rsplit("_", 1)[1]) for p in (out / "images" / "train").glob("*.jpg"))
    assert val_indices == [8, 9] and max(train_indices) < min(val_indices)


def test_images_without_labels_are_skipped_not_exported_as_negatives(tmp_path):
    data = tmp_path / "datasets"
    data.mkdir()
    _make(data, "backpack", 10000, 10, unlabelled=3)
    _registry(data, [("backpack", 10000)])
    summary = export_dataset(data, tmp_path / "out", 0.2)
    assert summary["skipped"] == 3
    assert sum(summary["counts"]["backpack"].values()) == 7


def test_a_small_dataset_gets_a_warning(tmp_path):
    data = tmp_path / "datasets"
    data.mkdir()
    _make(data, "backpack", 10000, 10)
    _registry(data, [("backpack", 10000)])
    assert any("only 10 photos" in w for w in export_dataset(data, tmp_path / "out")["warnings"])


def test_an_object_with_no_photos_is_left_out_and_class_numbers_stay_contiguous(tmp_path):
    data = tmp_path / "datasets"
    data.mkdir()
    _make(data, "truck", 10001, 10)
    _registry(data, [("ghost", 10000), ("truck", 10001)])
    summary = export_dataset(data, tmp_path / "out")
    assert summary["classes"] == ["truck"]
    assert "0: truck" in (tmp_path / "out" / "data.yaml").read_text()


def test_nothing_taught_is_a_clear_error(tmp_path):
    with pytest.raises(ValueError, match="nothing has been taught"):
        export_dataset(tmp_path, tmp_path / "out")
    data = tmp_path / "d2"
    data.mkdir()
    _registry(data, [("ghost", 10000)])
    with pytest.raises(ValueError, match="No labelled photos"):
        export_dataset(data, tmp_path / "out2")


def test_the_cli_reports_and_returns_a_status_code(tmp_path, capsys):
    data = tmp_path / "datasets"
    data.mkdir()
    _make(data, "backpack", 10000, 10)
    _registry(data, [("backpack", 10000)])
    assert main(["--datasets", str(data), "--out", str(tmp_path / "out")]) == 0
    assert "backpack: 8 train / 2 val" in capsys.readouterr().out
    assert main(["--datasets", str(tmp_path / "missing"), "--out", str(tmp_path / "o2")]) == 1


# --- custom label files for a retrained model -------------------------------

def test_default_labels_are_used_when_no_file_is_configured():
    assert load_class_names(None, ["person", "car"]) == ["person", "car"]
    assert load_class_names("", ["person"]) == ["person"]


def test_a_labels_file_is_read_one_name_per_line_in_order(tmp_path):
    path = tmp_path / "labels.txt"
    path.write_text("person\n\ncar\n backpack \n", encoding="utf-8")
    assert load_class_names(str(path), ["ignored"]) == ["person", "car", "backpack"]


def test_an_empty_or_missing_labels_file_fails_loudly(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("\n\n")
    with pytest.raises(ValueError):
        load_class_names(str(empty), [])
    with pytest.raises(FileNotFoundError):
        load_class_names(str(tmp_path / "nope.txt"), [])
