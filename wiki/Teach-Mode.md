# Teach Mode

The AI Camera's model is fixed on the sensor: it knows 90 everyday classes and cannot learn in flight. Teaching a new object is therefore two steps:

1. **Teach in the app** (immediate) - draw a box, name it. The Pi tracks it straight away with a visual tracker and saves labelled photos as you move around it.
2. **Retrain offline** (on a laptop) - the photos become a training set; a new model, once loaded onto the camera, detects the object on the sensor like any built-in class.

The drone never changes its own behaviour or limits as it "learns". Photos only feed your offline training, and you approve every model before it flies.

## Step 1 - Teach in the app

1. Fly tab → **TEACH NEW OBJECT** → drag a tight box around the object.
2. Name it (letters and numbers; stored as a lowercase label such as `red_backpack`, max 32 characters).
3. Optionally enter its **real width and/or height in metres**. This is the **only** way Follow can judge distance to it. Without a size the drone can turn toward it, but forward/back speed stays zero.
4. The Track / Follow / Orbit sheet opens. The chip shows `TEACHING: red_backpack (n)`, with *n* photos saved. Tap the chip to stop (this also ends tracking).

The Pi answers with `teach_result`. Failure reasons: `bad_box`, `bad_name`, `no_camera_frame` (sim, or the camera is not delivering pixels), `no_visual_tracker` (no OpenCV tracker installed), `box_too_small`, `box_outside_frame`.

### While teaching

- Tracking uses an OpenCV tracker (CSRT or KCF with the contrib build, else MIL), run on a worker thread so it cannot stall the control loop. Sanity limits reject implausible jumps in box size (1.8x) or shape.
- The appearance identity check still runs; if the box stops looking like the object, the drone holds.
- A photo is saved at most every 0.5 s, only when the box is fully in frame, still looks like the object (similarity ≥ 0.6) and has moved or changed size enough to not be a near-duplicate. Limits: 400 photos per object, 500 MB total.
- Follow/Orbit speed is capped at **1.5 m/s** - nothing but the tracker confirms it is still on the object.
- It is **not** an obstacle for the proximity check (the AI cannot see it) until a retrained model detects it.
- A lost object is **not** re-found automatically - draw the box again.

### Getting a good dataset

- **100+ photos per object, ideally 200-400**, across several sessions.
- Vary distance, angle, lighting and background. A model trained on one background learns the background.
- Include partial views, different heights, centred and near the frame edge.
- Teach **one object at a time** with nothing else you want detected in shot - other objects in the photo are unlabelled, which teaches the model to ignore them.
- If the photo count stops rising, the tracker has probably drifted - stop and redraw.
- Photos may contain people. They stay on the Pi (`companion/datasets/`, git-ignored) and are never uploaded by this software. Treat them as personal data.

## Step 2 - Export

Copy `companion/datasets/` to a laptop, then:

```bash
python tools/export_taught_dataset.py --datasets companion/datasets --out export/taught_v1
```

Writes a YOLO dataset (`images/`, `labels/`, `train`/`val`, `data.yaml`). The split is **chronological per object** (the last 20 % become validation), so near-identical consecutive frames never leak across it. Objects with under 100 photos get a warning.

## Step 3 - Train (laptop or cloud GPU, not the Pi)

> These training and conversion commands follow Ultralytics' and Raspberry Pi's published documentation; they have **not** been run in this project. Verify against current docs.

```bash
pip install ultralytics
yolo detect train data=export/taught_v1/data.yaml model=yolov8n.pt imgsz=320 epochs=100
```

**Do not lose the everyday classes.** A model trained only on taught objects forgets people and cars, and this system depends on `person` (Follow distance, obstacle check, tracking). Train on your objects **plus** a general set with at least `person`, `car`, `truck`, `bicycle`, `motorcycle`, using one consistent class list - or keep the stock model and use taught objects for tracking only.

Hold back photos from a **different day and place** as a real test set.

## Step 4 - Convert for the AI Camera

1. `yolo export model=best.pt format=imx data=export/taught_v1/data.yaml` (Linux/WSL2).
2. Package into a `.rpk` with Raspberry Pi's `imx500-package`.

For ONNX/TensorFlow models, `tools/imx500_convert.py` wraps Sony's converter (also unverified against the real CLI).

## Step 5 - Deploy and verify

1. Copy the `.rpk` to the Pi and write a **labels file**: one class name per line in class-index order, using exactly the taught names.
2. Edit `companion/config/hardware.yaml` (keep the old lines commented for a one-edit rollback):
   ```yaml
   camera:
     imx500_model_path: /home/omkar/ai-vision-drone/models/taught_v1.rpk
     labels_path: /home/omkar/ai-vision-drone/models/taught_labels.txt
     bbox_order: xy        # if the model emits (x0, y0, x1, y1)
     score_threshold: 0.35
   ```
3. `sudo systemctl restart ai-vision-drone`.
4. Verify on the bench, props off:
   - boxes land on the right objects and are not mirrored (hold a known object in one corner);
   - `tools/detection_regression.py` stability for people and cars is at least as good as the stock model;
   - the taught object is detected at working distances with few false positives;
   - its distance is within 15 % of a tape measure;
   - re-run lab checklist stages 6 and 7.

Once the model detects the object, it behaves like any class: tap-selectable, part of the obstacle check (its size is known), and tracked by the normal identity-checked tracker.

## Where things live

| Thing | Location |
|---|---|
| Photos and labels | `companion/datasets/<name>/{images,labels}/` |
| Registry (names, class ids, sizes) | `companion/datasets/taught_objects.json` |
| Tunables | `companion/config/teach_limits.yaml` |
| Code | `companion/learning/`, `tools/export_taught_dataset.py` |
| Session events | `teach_started`, `teach_failed`, `teach_target_lost` |
