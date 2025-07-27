Turtle Controller – Vision‑Only MVP Product Requirements Document (PRD)

Last updated: 27 Jul 2025

1  Purpose

Transform a Raspberry Pi 4 into an automated “smart terrarium” companion that:

Detects turtle movement with a 64 MP Arducam.

Builds a share‑worthy motion GIF.

Pushes the GIF to Telegram within 30 seconds.

Stores every motion frame + metadata locally for future Tiny‑YOLO re‑training.

(No relay control, sensors or RTC hardware—lightweight vision first.)

2  Goals & Success Metrics

Goal

Metric

Target

Timely alerts

GIF latency after motion

≤ 30 s for 95 % of events

Dataset creation

Unique labelled frames

≥ 10 k in 3 months

Reliability

Mean time between crashes

≥ 1 week continuous runtime

3  Scope (MVP)

Hardware

Raspberry Pi 4 (4 GB RAM or higher)

Arducam 64 MP CSI‑2 camera

(Optional) 5 V fan / heatsink for passive cooling

Software Components

Vision pipeline – Picamera2 preview → MotionDetector → CropStore → GIF Builder.

Telegram Bot – python‑telegram‑bot for commands & alerts.

Data Store – SQLite database + image/archive directory.

Systemd Services – each component runs as a managed unit (see §4.4).

Time Sync – NTP via systemd-timesyncd; no RTC fallback.

Out of Scope: environmental sensing, relay control, cloud sync, GPU acceleration, multi‑camera.

4  Functional Requirements

4.1 Vision & Alerts

Frame rate – Preview at ≥ 10 FPS (640 × 480).

Motion detection – Background subtraction with morphological filtering.

Trigger when blob area > 1000 px² and motion intensity > configurable threshold.

Dynamic cropping – Request full‑res crop (64 MP) with 15 % margin around the bounding box to keep the turtle centred.

Buffering – Push crops to an in‑memory ring buffer.

Inactivity timeout – If no new motion for 6 s (configurable), close the event.

GIF assembly

Down‑sample to ≤ 1920 px width.

Max 16 frames at 4 FPS → playback length ≤ 4 s.

For longer events, decimate frames (skip every n) to stay under 16‑frame cap.

Alert – Post GIF to Telegram chat with timestamp caption.

Persistence – Save each crop as JPEG + JSON (timestamp, bbox) in /var/lib/turtle/frames/<date>/.

4.2 Telegram Bot Commands

Command

Description

/photo

Capture & send a full‑res still

/gif N

Assemble and send last N buffered frames (default 10)

/help

List available commands

4.3 Data Collection for ML

Store every triggering preview frame + bbox.

Nightly turtle_pack.service compresses the day’s frames into a YYYY‑MM‑DD.tar.zst archive.

export_yolo.py converts archives → YOLO images/ & labels/ for re‑training.

4.4 Systemd Services

Each component is deployed as its own unit:

Unit

Type

Key Options

turtle_motion.service

simple

ExecStart=/usr/bin/python3 motion_detector.py   Restart=on-failure RestartSec=3

turtle_gif.service

oneshot

Triggered by motion via systemd-run or /gif command

turtle_bot.service

simple

ExecStart=/usr/bin/python3 telegram_bot.py  After=network-online.target

turtle_pack.timer & .service

timer

Packs & rotates archives daily at 02:00

Common hardening for all units:

[Service]
User=turtle
Group=turtle
LimitNOFILE=4096
ProtectSystem=strict
ReadWritePaths=/var/lib/turtle
CPUAccounting=yes
MemoryAccounting=yes
StandardOutput=journal

5  Non‑Functional Requirements

Performance – Pi CPU < 60 %, RAM < 2 GB.

Storage – Auto‑delete or compress vision data older than 30 days or when disk usage > 80 %.

Maintainability – Python 3.12, PEP‑8, MIT licence, GitHub CI (ruff, pytest).

Security – Bot token in .env (600 permissions); systemd ProtectSystem.

Reliability – All services Restart=on-failure; systemd watchdog optional.

6  Architecture Overview

Pi 4
├── picamera2 → MotionDetector → CropStore
│                               ↘ GIF Builder → Telegram Bot
└── nightly turtle_pack.timer → Archive → SQLite index

Replacing MotionDetector with Tiny‑YOLO later keeps upstream/downstream unchanged.

7  Data Model (SQLite)

CREATE TABLE detections (
  ts         DATETIME PRIMARY KEY,
  bbox_x     INTEGER,
  bbox_y     INTEGER,
  bbox_w     INTEGER,
  bbox_h     INTEGER,
  confidence REAL DEFAULT 1.0,
  img_path   TEXT
);

8  Milestones & Timeline (4 weeks)

Week

Deliverable

1

Hardware & OS; camera streaming preview

2

Motion detection + CropStore saving locally

3

GIF builder + Telegram alerts; all systemd units active

4

48‑h soak test; doc + v0.1 tag

9  Risks & Mitigations

Risk

Impact

Mitigation

Pi overheats during CV

System hang

Heatsink/fan; CPU governor

Disk fills with images

Alerts stop

30‑day rotation + 80 % threshold

Telegram API limits

Missed alerts

Exponential backoff; still‑image fallback

False positives (reflections)

Spam GIFs

Threshold tuning; future Tiny‑YOLO

10  Future Considerations

Replace background subtraction with Tiny‑YOLO.

Coral / Pi AI Kit for 30 FPS.

Cloud sync & dashboard.

Multi‑camera support

