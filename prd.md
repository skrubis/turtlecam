Turtle Controller – MVP Product Requirements Document (PRD)

1. Purpose

Build a minimum‑viable product that transforms a Raspberry Pi‑based setup into an automated “smart terrarium” for a single turtle.  The system must:

Monitor the animal with a 64 MP Arducam and automatically share motion GIFs via Telegram.

Control lighting/heat via relays, guided by a DHT22 temperature–humidity sensor.

Persist sensor and vision data so a future release can retrain a single‑class Tiny‑YOLO model for more robust turtle detection.

2. Goals & Success Metrics

Goal

Metric

Target

Timely alerts

GIF posted to Telegram after motion

< 30 s latency 95 % of events

Environmental stability

Temp inside 24 – 30 °C

95 % of the time

Data for future ML

Number of labelled frames

≥ 10 k unique frames in 3 months

Reliability

Mean time between crashes

≥ 1 week continuous runtime

3. Scope (MVP)

Hardware

Raspberry Pi 4 (4 GB RAM+)

Arducam 64 MP CSI‑2 camera

DHT22 temperature‑humidity sensor

2–4 ch 5 V relay board (lights, heater, fan)

Optional 5 V fan for Pi cooling

Optional DS3231 RTC hardware clock for offline time‑keeping

Software Components

Vision pipeline – Picamera2 preview (640×480) → motion detector → full‑res crop → GIF.

Telegram Bot – python‑telegram‑bot for commands & alerts.

Env Monitor – DHT22 polling, thresholds, logging.

Relay Controller – scheduled + manual switching.

Data Store – SQLite DB + image/archive directory.

System Services – systemd units & YAML config.

Time Sync – chrony/NTP service with DS3231 RTC fallback.

Out of Scope (MVP)

Cloud backup / remote firmware update.

Coral / GPU acceleration.

Multi‑turtle or multi‑camera support.

4. Functional Requirements

4.1 Vision & Alerts

Capture preview at ≥ 8 FPS; detect motion via background subtraction.

When bbox area > 800 px²:

Request 64 MP crop using ScalerCrop ROI.

Append to in‑memory buffer.

After N s of inactivity (configurable, default 8 s):

Assemble GIF (≤ 4 FPS, max 20 frames, 1920 px wide).

Post to Telegram chat.

Save each crop as JPEG + JSON metadata (timestamp, bbox).

4.2 Environmental Monitoring

Poll DHT22 every 60 s.

Log timestamp, temp (°C), humidity (%) to SQLite.

Alert Telegram if temp < 22 °C or > 33 °C.

4.3 Relay Control

Two named channels: daylight, uv_heat (+ optional fan).

YAML schedule (cron‑style) with default:

daylight: 08:00–20:00

uv_heat: 09:00–18:00

Manual overrides via bot commands (/relay <name> on|off).

Safety: auto‑OFF if temp > 35 °C for > 5 min.

4.4 Telegram Bot Commands

Command

Response

/status

Current temp/humidity + relay states

/photo

Instant still capture

/gif N

Force GIF of last N frames (default 10)

/relay <name> on/off

Toggle relay

/help

Command list

4.5 Data Collection for ML

Store every preview frame that triggered motion plus its bbox.

Daily job packs frames into date‑stamped TAR file.

Provide script export_yolo.py → images & YOLO txt labels for retraining.

4.6 Time Synchronization

System clock shall synchronise via chrony/NTP at boot and every hour thereafter.

If the network is unavailable, read time from the DS3231 RTC module; write‑back when the link returns.

All scheduled relay actions and data timestamps must rely on the synced clock.

Clock accuracy requirement: drift < ±60 s after 24 h of network loss.

4.7 Enhanced Relay Control

Option to derive daylight and uv_heat schedules automatically from calculated sunrise/sunset for a user‑configured location.

Fallback to the YAML cron schedule when geolocation is not set or calculation fails.

5. Non‑Functional Requirements Non‑Functional Requirements

Performance: Average Pi CPU usage < 60 %, memory < 2 GB.

Storage: Auto‑delete/raw compress vision data older than 30 days or when disk > 80 %.

Maintainability: Code in Python 3.12, PEP‑8, MIT licence, GitHub CI (ruff, pytest).

Security: Bot token stored in .env file, file permissions 600.

Reliability: System recovers on power loss; services Restart=on-failure.

6. Architecture Overview

Pi 4
├── picamera2  ↣  MotionDetector  ↣  CropStore
│                               ↘  GIF Builder ↣ Telegram
├── DHT22 Poller ↣ SQLite ↣ Alerting (temp)
└── RelayAgent  ← Schedules / Bot commands

Modular design means swapping MotionDetector with Tiny‑YOLO Detector later only touches that component.

7. Data Model (SQLite)

CREATE TABLE env_log (
  ts            DATETIME PRIMARY KEY,
  temp_c        REAL,
  humidity_pct  REAL
);

CREATE TABLE detections (
  ts            DATETIME PRIMARY KEY,
  bbox_x        INTEGER,
  bbox_y        INTEGER,
  bbox_w        INTEGER,
  bbox_h        INTEGER,
  confidence    REAL DEFAULT 1.0 -- placeholder for YOLO later,
  img_path      TEXT
);

8. Milestones & Timeline (6 weeks)

Week

Deliverable

1

Hardware assembled, OS flashed, camera + DHT22 verified

2

Motion‑detect prototype saves crops locally

3

GIF builder & Telegram bot push alerts

4

Relay schedules + manual bot control

5

Data logging, rotation & config YAML

6

End‑to‑end soak test 48 h, documentation, v0.1 tag

9. Risks & Mitigations

Risk

Impact

Mitigation

Pi overheats running CV + GIF

System crash

Heatsink + fan, CPU governor

=

Disk fills with images

Alerts stop

Rollover + age‑based deletion

Telegram API rate limits

Lost notifications

Backoff + still‑image fallback

False positives (reflections)

Spam GIFs

Threshold tuning, future Tiny‑YOLO

10. Future Considerations (Post‑MVP)

Tiny‑YOLO Detector – fine‑tune single‑class model with collected dataset; drop background subtractor.

Edge Acceleration – explore USB Coral or Pi AI Kit for 30 FPS.

Cloud Sync & Dashboard – push metrics to InfluxDB / Grafana Cloud.

Multi‑camera Support – add overhead/basking camera views.

Last updated: 27 Jun 2025

