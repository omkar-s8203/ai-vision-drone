# Teach mode: teaching the drone new objects

**What this is.** The Raspberry Pi AI Camera runs a fixed neural network *on the sensor*
(the stock model knows 90 everyday classes: people, cars, bikes...). That network cannot
learn while flying, so teaching a new object is two steps:

1. **Teach in the app (immediate, works today).** You draw a box around any object and
   name it. The Pi tracks it right away with a class-agnostic visual tracker and saves
   labelled photos of it as you move around it.
2. **Retrain (offline, on a laptop).** The saved photos become a training set. A newly
   trained model, once loaded, detects the new object on-sensor at full speed like any
   built-in class.

**What this is not.** The drone does not change its own behaviour or safety limits as it
"learns". Taught-object photos only ever feed *your* offline training; you review and
approve every model before it goes on the aircraft.

---

## Step 1 - Teach it in the app

1. Fly tab -> **TEACH NEW OBJECT** (top-left chips) -> drag a tight box around the object.
2. Name it (letters/numbers; it is stored as a lowercase label such as `red_backpack`).
3. Enter the object's **real size in metres** (width and/or height). This is optional but
   it is the **only** way Follow can judge distance to it. Without it the drone can turn
   toward the object but its forward/back speed stays at zero.
4. The Track / Follow / Orbit sheet opens as with any target. The chip shows
   `TEACHING: red_backpack (n)` where *n* is the number of photos saved. **Tap the chip to
   stop teaching** (this also ends tracking).

### What the drone does while teaching

- Tracks the object with an OpenCV visual tracker (not the AI chip).
- Saves a photo + box label when the track still *looks like* the object, the object has
  moved or changed size (no near-duplicates), and the box is fully inside the frame -
  at most twice a second, 400 photos per object, 500 MB total (`teach_limits.yaml`).
- Follows/orbits it **slower** than a normal target (1.5 m/s cap) because nothing but the
  tracker confirms it is still on the object.
- Does **not** treat it as an obstacle (the AI chip cannot see it, so the proximity check
  cannot either) - until a retrained model detects it.

### Limits you should know

| Limit | Why / what to do |
|---|---|
| A lost object is **not re-found automatically** | No detector to find it again. The chip clears; draw the box again. |
| The tracker can **drift** onto background | Mitigated by the appearance check (drops to a hold when the box stops looking like the object), sanity limits on box size/shape and the lower speed cap - but treat taught-object Follow as **less reliable than a detected person**. Test it on the bench first. |
| Tracker speed | Stock OpenCV has only the MIL tracker (~35 ms/frame on a laptop CPU; measure on the Pi). It runs on a worker thread so it cannot stall the control loop. `pip install opencv-contrib-python-headless` on the Pi gives the better/faster CSRT/KCF, which are used automatically when present. |
| Labels are single-object | Each photo labels only the taught object; other things in the picture (a person beside a backpack) are unlabelled, which teaches the model to ignore them. **Teach one object at a time, against varied backgrounds, with nothing else you want detected in shot.** |
| Photos may show people | They are saved on the Pi (`companion/datasets/`, git-ignored) and never uploaded by this software. Treat them as personal data. |

### How to capture a good dataset (this decides the model quality)

- **100+ photos per object, ideally 200-400**, from **several sessions**.
- Vary **distance** (near and far), **angle** (all sides), **lighting** (sun/shade/dusk) and
  **background** (grass, tarmac, buildings). A model trained on one background learns the
  background.
- Include the object partly turned, at different heights (walk the drone/camera around it),
  and both centred and toward the frame edges.
- Do not include a second instance of the same kind of object that you do *not* want
  detected (e.g. teach "my truck" with no other trucks in view).
- Photos are only saved while the track matches the object (histogram similarity >= 0.6),
  so if the count stops rising the tracker has probably drifted - stop and re-draw.

---

## Step 2 - Export the photos

Copy `companion/datasets/` from the Pi to your laptop, then:

```bash
python tools/export_taught_dataset.py --datasets companion/datasets --out export/taught_v1
```

This writes `export/taught_v1/{images,labels}/{train,val}` and a `data.yaml`. The
train/validation split is **chronological per object** (the last 20 % become validation) so
near-identical consecutive frames never leak across the split. It warns about objects with
under 100 photos and skips images that have no label.

---

## Step 3 - Train (on a laptop or free cloud GPU - not on the Pi)

**Verification status: the commands below follow Ultralytics' and Raspberry Pi's published
documentation. I could not run training or the IMX500 conversion on this machine, so treat
them as a checked starting point, not a tested recipe - verify each step against the
current docs for the versions you install.**

Suggested route (YOLOv8n, small enough for the sensor):

```bash
pip install ultralytics
yolo detect train data=export/taught_v1/data.yaml model=yolov8n.pt imgsz=320 epochs=100
```

### Do not lose the everyday classes

A model trained **only** on your taught objects will *forget* people, cars, etc. - and this
system relies on `person` (Follow's distance, the obstacle check, tracking). Either:

- **(recommended)** train on a **merged dataset**: your taught objects **plus** a general
  detection set covering the classes you still need (a COCO subset containing at least
  `person`, `car`, `truck`, `bicycle`, `motorcycle`), with one consistent class list; or
- keep the stock model and treat taught objects as tracking-only (Step 1).

Hold out some photos taken on a **different day / place** as a test set - validation photos
from the same session overstate how well it will work in the field.

---

## Step 4 - Convert for the AI Camera

Per Ultralytics' and Raspberry Pi's documentation (verify against current versions):

1. Export for the IMX500 (needs Linux/WSL2): `yolo export model=best.pt format=imx data=export/taught_v1/data.yaml`
2. Package the result into a `.rpk` with Raspberry Pi's `imx500-package` tool.

For other toolchains (an ONNX/TensorFlow model), `tools/imx500_convert.py` wraps Sony's
converter (see its docstring - also unverified against the real CLI).

---

## Step 5 - Deploy and verify

1. Copy the `.rpk` to the Pi and create a **labels file**: one class name per line, in the
   model's class-index order. **Use exactly the taught names** (the lowercase labels the
   export wrote to `data.yaml`) so the real sizes you entered are applied for distance.
2. Edit `companion/config/hardware.yaml`:
   ```yaml
   camera:
     imx500_model_path: /home/omkar/ai-vision-drone/models/taught_v1.rpk
     labels_path: /home/omkar/ai-vision-drone/models/taught_labels.txt
     bbox_order: xy      # if the model emits (x0, y0, x1, y1); default yx is the stock SSD order
     score_threshold: 0.35
   ```
   Keep the previous values commented in the file so you can **roll back in one edit**.
3. `sudo systemctl restart ai-vision-drone`.
4. **Verify before trusting it (bench, props off):**
   - Boxes land on the right objects and are not mirrored/swapped (a wrong `bbox_order`
     looks plausible but is wrong - hold a known object in a corner of the frame).
   - `python tools/detection_regression.py capture ...` / `analyze ...`: detection rate and
     stability at least as good as the stock model for **people and cars**.
   - The taught object is detected at your working distances, and **false positives** are
     rare (walk around the site with the camera and watch for phantom detections).
   - Distance for the taught object is within 15 % of a tape measure (lab checklist 6B).
   - Re-run the relevant lab checklist stages (6, 7) before any flight with the new model.

Once the new model detects a taught object, the normal machinery applies: it can be
selected by tap, it counts for the obstacle-proximity check (its real size is known), and
it is tracked by the same identity-checked detector-based tracker as a person.

---

## Where things live

| Thing | Location |
|---|---|
| Photos + labels | `companion/datasets/<name>/{images,labels}/` (git-ignored) |
| Registry (names, class ids, real sizes) | `companion/datasets/taught_objects.json` |
| Tunables | `companion/config/teach_limits.yaml` |
| Session log events | `teach_started`, `teach_failed`, `teach_target_lost` |
| Code | `companion/learning/`, `tools/export_taught_dataset.py` |
