# AI Vision Drone

An AI companion-computer upgrade for an existing, already-flying RC multicopter. A **Raspberry Pi 5** with the **Raspberry Pi AI Camera** (Sony IMX500) watches the scene, tracks a target the operator picks, and proposes flight commands to an **ArduPilot** flight controller. A native **Android Ground Station** app shows live video, lets the operator pick and manage targets, and shows telemetry and health.

The original flight chain is untouched: RC transmitter → receiver → flight controller → ESCs → motors. The Pi never drives the motors directly. It can only suggest velocity setpoints while the flight controller is in `GUIDED` mode, and the pilot's transmitter mode switch takes control back at any moment, whether or not the Pi is running.

> **Guiding priority:** STABLE → LOW LATENCY → ACCURATE → EFFICIENT → SAFE.
> The flight controller is the only flight authority. RC override never depends on the Pi being alive.

## What it can do

| Capability | Summary | Page |
|---|---|---|
| On-sensor object detection | 90 COCO classes (people, cars, bikes, ...) detected on the camera chip itself, ~27 FPS | [Vision and Detection](Vision-and-Detection) |
| Tap-to-track | Tap or drag on the video to pick a target; the tracker holds it and checks it is still the same person | [Tracking and Target Selection](Tracking-and-Target-Selection) |
| Follow / Orbit | Keep a set distance from the target, or circle it | [Guidance Modes](Guidance-Modes) |
| Arm & Follow | Arm, climb to a safe height, then start following | [Guidance Modes](Guidance-Modes#arm--follow-auto-takeoff) |
| Grid Search | Fly a lawnmower sweep over an area from GPS waypoints | [Guidance Modes](Guidance-Modes#grid-search) |
| Target-loss recovery | Search, then return home, or land only if the operator approves | [Guidance Modes](Guidance-Modes#target-loss-recovery) |
| Approach-Test | A tightly bounded approach to a test fixture, for controlled experiments only | [Guidance Modes](Guidance-Modes#approach-test) |
| Teach mode | Draw a box around any object, name it, track it, and collect training photos | [Teach Mode](Teach-Mode) |
| Safety supervisor | One gate decides whether any command reaches the flight controller | [Safety Architecture](Safety-Architecture) |
| Offline operation | No internet needed to fly - the Pi, phone and FC talk over a local link only | [System Architecture](System-Architecture#offline-by-design) |

## What it is not

- Not a replacement flight controller and not a motor controller.
- Not an obstacle-avoidance system. Obstacle detection is vision-only and class-based: it sees people and vehicles, not walls, trees, poles, wires or glass.
- Not a weapon or an autonomous targeting system. The perimeter alert in the app is a situational-awareness feature only.

## Where to start

| You want to... | Go to |
|---|---|
| Understand how the pieces fit | [System Architecture](System-Architecture) |
| Build the hardware | [Hardware Setup](Hardware-Setup) |
| Install everything from a blank SD card | [Installation](Installation) |
| Run it (sim or real hardware) | [Running the Companion](Running-the-Companion) |
| Use the phone app | [Android Ground Station](Android-Ground-Station) |
| Test before flying | [Lab Testing and Flight Readiness](Lab-Testing-and-Flight-Readiness) |
| Change a limit or threshold | [Configuration Reference](Configuration-Reference) |
| Work on the code | [Developer Guide](Developer-Guide) |
| Fix a problem | [Troubleshooting](Troubleshooting) |
| See what is done and what is next | [Project Status and Roadmap](Project-Status-and-Roadmap) |

## Current status in one paragraph

Roughly **72 % complete**. All software is written and tested (763 companion tests passing). The camera, on-sensor AI, video, MAVLink telemetry, arm/disarm and flight-mode control have all run together on the real Pi and flight controller, mounted on the aircraft with props off. **No guidance velocity command has yet been sent to the real flight controller**, the transmitter override switch (`FLTMODE_CH`) is not yet configured, and the camera has not been calibrated. Real flight has not started. See [Project Status and Roadmap](Project-Status-and-Roadmap).

## Repository

Source: <https://github.com/omkar-s8203/ai-vision-drone> (branch `master`).

```
companion/   Python 3.11+ asyncio app on the Pi (vision, tracking, guidance, MAVLink, comms, safety)
android/     Native Kotlin / Jetpack Compose Ground Station app
sim/         Mock flight controller, real-SITL launcher, synthetic target generator
tools/       Calibration, benchmarking, dataset export, live monitor
deploy/      systemd unit for the Pi
docs/        Protocol spec, safety case, wiring notes, lab checklist, Teach-mode guide
```
