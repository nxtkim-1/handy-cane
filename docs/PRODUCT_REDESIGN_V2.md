# HandyCane v2 — Biomedical Product, Ergonomic, Electronics & Mechanical Redesign Specification

**Project:** HandyCane (`nxtkim-1/handy-cane`)  
**Document ID:** `HC-SPEC-V2-001` (Rev A)  
**Author:** Thomas Kim  
**CAD & Verification Suite:** [`hardware/cad_v2/`](../hardware/cad_v2/) · [`hardware/fusion360/HandyCaneV2_ImportAndParams/`](../hardware/fusion360/HandyCaneV2_ImportAndParams/)

---

## 0. Scope, Architectural Continuity & Evidence Hygiene

HandyCane's core product constraint remains unchanged from [`docs/ARCHITECTURE.md`](ARCHITECTURE.md):

> **The cane asks locally first (`"Are you okay? Press the button if you are fine."`), escalates only when nobody answers, logs objective cane-use trends against the user's own baseline, and makes zero clinical or diagnostic claims.**

This specification documents the complete **v2 mechanical, ergonomic, acoustic, power, and embedded electronics redesign** transforming HandyCane from a hackathon proof-of-concept (an exposed Raspberry Pi 4B tray and a 10,000 mAh USB power-bank tray zip-tied to an aluminum cane shaft) into a compact, balanced, splash-protected, manufacturable assistive product.

### 0.1 Repository & Branch Baseline Audit
- **`main` (`75f620a`)**: Contains the canonical architecture decision record ([`docs/ARCHITECTURE.md`](ARCHITECTURE.md)), the v1 printed tray STLs ([`hardware/cad/`](../hardware/cad/)), the Pi detector/link runtime ([`pi/`](../pi/)), the CaneSense FSM/outbox ([`cane/`](../cane/)), the FastAPI backend ([`backend/`](../backend/)), and the Expo companion app ([`mobile/`](../mobile/)).
- **`origin/review/integration-plus-dev-clean` (`14eaa6c`)**: Adds `GET /live` 1 Hz live-posture telemetry (`cane/canesense/live.py`, `mobile/src/comm/liveView.ts`), session evaluation tooling (`tools/session_format.md`), and the volunteer crash-mat collection protocol (`docs/DATA_COLLECTION.md`), while keeping identical core wire contracts in [`mobile/PROTOCOL.md`](../mobile/PROTOCOL.md) and [`mobile/src/comm/BleCaneTransport.ts`](../mobile/src/comm/BleCaneTransport.ts).
- **v2 Branch Strategy**: `cad/v2-ergonomic-redesign` branches cleanly off `main` (preserving `hardware/cad/` v1 meshes for automated side-by-side inertia verification) while designing the v2 BLE GATT firmware interface to support both the core `HELLO / TIME_SYNC / PULL / ACK / ALERT` contract and the 1 Hz `LIVE` snapshot stream from `review/integration-plus-dev-clean`.

### 0.2 Evidence Tagging Taxonomy
Every engineering claim in this document and in [`hardware/cad_v2/verification_v2.json`](../hardware/cad_v2/verification_v2.json) is tagged with one of three strict verification labels:
- **`[CAD/ANALYTICAL]`**: Mathematically verified directly on the exported OpenCascade B-Rep `.step` / watertight `.stl` models, closed-form solid mechanics, or published IC datasheet electrical parameters.
- **`[SIMULATED]`**: Verified in deterministic software simulation / recorded sensor session replay (`tests/cane_regression_tests.py`, `tests/canelink_adapter_tests.py`, `cane/tests/`).
- **`[PHYSICAL-PENDING]`**: Requires physical bench, environmental chamber, accredited mechanical test-rig, acoustic SPL meter, or IRB/ethics-approved human-factors validation before claiming compliance.

---

## 1. Quantitative Audit of v1 Failure Modes

Direct geometric inspection of the v1 CAD meshes in [`hardware/cad/`](../hardware/cad/) reveals six severe assistive-device failure modes (`[CAD/ANALYTICAL]`):

| Failure Mode | v1 Hackathon Build (`hardware/cad/`) | Biomechanical / Reliability Consequence |
|---|---|---|
| **1. Excessive Distal Mass & Pendulum Swing Inertia** | `pi_cane_case.stl` (`222.4 × 68.8 × 45.1 mm`, `95.52 cm³`) at `z = 614 mm` + `bank_holder.stl` (`137.6 × 69.8 × 33.5 mm`, `61.74 cm³`) at `z = 410 mm` + Pi 4B/Hat (`112 g`) + 10 Ah USB bank (`225 g`) = **`460.8 g` added mass** (`+142%` over `323.8 g` cane). | Hanging `277 g` (`bank + tray`) at `r = 476 mm` below the wrist pivot (`z = 886 mm`) creates **`75,859 kg·mm²` (`0.0759 kg·m²`)** of added wrist swing inertia—more than **doubling** cane swing effort across 2,000–4,000 daily strides for users with neuromuscular weakness (e.g., 4/5 grip strength in limb-onset ALS). |
| **2. Eccentric `+X` Gravity Torque** | Both trays hang exclusively forward of the shaft (`CoM_x = +20.78 mm`). | Generates a persistent off-axis pronation/flexion wrist moment when tilted and causes the cane to roll violently onto its face when set down. |
| **3. Zip-Tie Viscoelastic Creep & IMU Drift** | Nylon PA66 zip ties cinched over smooth anodized aluminum (`μ ≈ 0.18`, zero torsional key, zero elastomer preload). | Under repeated `2–6 g` ground strikes, zip ties creep and slip circumferentially/axially, corrupting the calibrated upright gravity vector `u` in [`pi/detector.py`](../pi/detector.py) and causing tray rattle that triggers false strikes (`STRIKE_G = 0.45 g`). |
| **4. Snag Hazard & Bulk Footprint** | `69.8 mm` wide open box spanning `370.6 mm` of the upper shaft (`z = 341–712 mm`). | Catches on stair balusters, chair armrests, car door frames, and kitchen counters—creating an active trip/drop hazard. |
| **5. Open Unsealed Electronics (`IP00`) & Short Runtime** | Open-top trays expose Pi 4B 40-pin header, Grove cables, and USB ports; Pi 4B draws `~3.0–3.5 W` continuous. | Vulnerable to rain, snow, and kitchen splashes; heavy `37 Wh` USB bank depletes in **`~11.2 hours`** (`< 1 waking day`), with SD-card corruption risk on brownout and no `RTC` across reboots. |
| **6. Generic Cylindrical Foam Grip** | Plain `Ø31 mm` cylindrical foam sleeve with externally zip-tied Grove button cable. | Concentrates palmar reaction force onto a narrow line over the carpal tunnel / median nerve, induces ulnar deviation, and exposes an external wire loop to snagging. |

---

## 2. Standards & Biomedical Human Factors Architecture

### 2.1 Structural & Tip Standards Framing (`ISO 11334-4` & `ISO 24415-1`)
1. **ISO 11334-4 / ISO 11334-1 (Walking Aids Manipulated by One Arm)**:
   - **Requirement Framing**: Walking sticks and offset canes must withstand a static vertical proof load of **`>= 1,000 N`** (`~102 kgf`) applied through the handgrip without fracture or permanent deformation exceeding tolerance, plus cyclic fatigue loading (`200,000+` cycles at `800–1,000 N`) `[TO VERIFY: confirm exact proof load and cycle count against the purchased ISO 11334-4 text; these values are working assumptions]`.
   - **v2 Structural Engineering Rule**: **3D-printed polymer is strictly forbidden from carrying unbacked primary axial or bending body weight.** HandyCane v2 routes 100% of primary ground-reaction force through a **continuous, unbroken `Ø22.0 × 2.0 mm` seamless drawn 6061-T6 aluminum tube** that runs continuously from the lower telescoping lock collar (`z = 306 mm`), through the `C¹` swan-neck offset curve (`z = 764–886 mm`), and straight through the core of the horizontal handle (`z = 886 mm, x = -32 to +96 mm`) with **zero drilled holes** (avoiding a `Kt ≈ 3.0` cross-hole stress raiser).
   - **Analytical vs Lab Boundary**: Section 4.3 verifies straight-shaft and swan-neck bend combined axial/bending stress, polymer-over-core compressive bearing stress (`0.41 MPa`), and Euler buckling (`[CAD/ANALYTICAL]`). The static proof test itself and cyclic fatigue certification at the bend require physical laboratory rig testing on commercial drawn cane tubing (`[PHYSICAL-PENDING]`).
2. **ISO 24415-1 (Tips for Assistive Products for Walking — Friction Determination)**:
   - Specifies dynamic/static slip-resistance testing of rubber ferrules on dry/wet smooth surfaces. HandyCane v2 leaves the lower `Ø19.0 mm` (`3/4 in`) telescoping shaft completely unmodified below `z = 636 mm`, retaining full compatibility with standard replacement **ISO 24415-1 compliant flared treaded rubber tips** (`Ø38 mm` ground contact face with concentric water-evacuation channels modeled in `ref_ferrule_tip.step`; wet-tile friction testing `[PHYSICAL-PENDING]`).

### 2.2 Ergonomic Hand Anthropometry (5th-Percentile Female to 95th-Percentile Male)
Using adult hand anthropometry (ANSUR II / Tilley, *The Measure of Man and Woman*, including older-adult arthritic clearance allowances):
- **Hand Breadth (Metacarpal)**: `74 mm` (5th %ile female) to `98 mm` (95th %ile male); **Contoured Grip Length (`128.0 mm`, `x = -24 to +104 mm`)** provides `15–27 mm` axial margin at both ends including a closed `7.55 mm` solid polymer rear safety pommel.
- **Swan-Neck Colinear Load Vector Alignment**: The `50°` `C¹` swan-neck offset positions the primary **3rd-metacarpal / capitate / ulnar styloid load axis** directly over the vertical cane shaft centerline (`x = 0 to +18 mm`). Ground-reaction forces pass straight through the forearm's neutral skeletal column (`~7°` neutral wrist pitch), minimizing wrist extension/ulnar torque.
- **Broad Ambidextrous Palmar Shelf (`44.4 mm` Palm / `46.0 mm` Hypothenar Flare)**:
  - Replaces v1's `Ø31 mm` foam cylinder with a multi-station lofted anatomical palm deck (`44.4 mm` wide at `x = +28 mm`, flaring to `46.0 mm` at the hypothenar heel `x = +72 mm`, with subtle index/middle finger saddles underneath).
  - Increases effective palmar bearing contact area from `~13 cm²` to **`~27 cm²` (`~2.1×`)** `[CAD/ANALYTICAL]`, cutting peak palmar tissue pressure under a typical `300 N` (`30% BW`) stance load from `~230 kPa` to **`~110 kPa`**—reducing median-nerve compression over the carpal tunnel.
  - **Clinical Contralateral Prescription**: Because a cane is prescribed in the hand *opposite* the weaker leg (e.g., left-hand grip for right foot drop in the patient brief), the palmar shelf uses **symmetric bilateral wings (`y = ±22.2 mm`)** so one geometry serves both left- and right-handed users without hand-specific SKU lock-in.

### 2.3 Tactile Dual-Action Cancel / SOS Interface
- **Placement**: Centered on the natural distal thumb deck (`x = -4.0 mm, y = 0.0 mm`), reachable with zero grip repositioning.
- **Anti-Accidental-Press Guard Ring**: Raised `Ø21.0 mm` (`ID 14.6 mm`) circular bezel integrated into `grip_upper` whose top rim (`z = 910.2 mm`) stands **`2.00 mm` proud** of the `Ø13.8 mm` button cap (`z = 908.2 mm`). Resting the cane upside-down or hooking it over a counter edge contacts only the rigid bezel (`0.0 mm` switch travel) `[CAD/ANALYTICAL]`.
- **Tactile & Visual Accessibility**: High-contrast **Safety Coral (`#D94F30`)** concave thumb dish (`0.75 mm` blind-centering dimple) over an IP67 sealed `12 × 12 mm` tactile switch (`3.5 N` crisp snap, `0.35 mm` travel). Preserves the exact firmware interaction contract:
  - **Short press (`50 ms – 2.0 s`)**: Immediate `OK_PRESS` (`1500 Hz` 80 ms confirmation chirp + `"Okay. Alert cancelled."`).
  - **Sustained hold (`>= 2.0 s`)**: Rising-pitch countdown chirps every `500 ms` (`800 -> 1800 Hz`) so the user hears the hold progressing, firing `SOS_HOLD` at `2.0 s` (`2200 Hz` tone + `"Help is being called. Hold on."`).
  - **Parked Lockout**: Ignored when `dyn_avg < 0.015 g` upright for `> 3 s` (unless `down == True`, preserving the post-fix safety exemption verified in [`tests/cane_regression_tests.py`](../tests/cane_regression_tests.py)).

### 2.4 Environmental Ingress & Mechanical Durability (`IP54` Target)
- **Seam Sealing**: `pod_front_shell` and `pod_rear_shell` mate along a **continuous tongue-and-groove peripheral labyrinth** (`1.10 mm` tongue inside `1.60 mm` groove, `0.25 mm` clearance, sized to accept a `Ø1.0 mm` Shore 50A silicone O-ring cord for splash/dust sealing).
- **Protected Charging Port**: Bottom-recessed 16-pin USB-C receptacle sealed during walking/outdoor use by a dual-step **Shore 85A TPU ingress plug** (`usbc_dust_plug`).
- **Sealed Acoustic Aperture**: **IP67-rated mylar-diaphragm speaker** (`CUI CMS-28588N-L152`) sealed against the internal `Ø25.2 mm` bezel ledge so moisture entering the exterior acoustic louvres cannot enter the PCB cavity (`[PHYSICAL-PENDING]` IEC 60529 IP54 verification).

---

## 3. Electronics, Power, Acoustic & BLE Wire Architecture

### 3.1 Embedded MCU Trade Study (`nRF52840` vs `ESP32-S3` vs `v1 Pi 4B`)

| Criterion | v1: Raspberry Pi 4B | Candidate A: Espressif ESP32-S3 (XIAO ESP32S3) | **Selected v2: Nordic nRF52840 (Seeed XIAO nRF52840)** |
|---|---|---|---|
| **Core & Clock** | Quad Cortex-A72 @ 1.5 GHz (Linux) | Dual Xtensa LX7 @ 240 MHz | **ARM Cortex-M4F @ 64 MHz (Hardware FPU)** |
| **Wireless** | Wi-Fi + BT 5.0 | Wi-Fi 4 + BLE 5.0 | **BLE 5.3 (native low-energy stack)** |
| **System Idle + 100 Hz IMU Polling Current** | `~620 mA @ 5 V` (`3,100 mW`) | `~14–22 mA @ 3.7 V` (`~65 mW` BLE modem-sleep + DMA) | **`~0.95 mA @ 3.7 V` (`3.5 mW` System-ON idle + I2C/SPI FIFO wake)** |
| **BLE Connected Sync Current (1 Hz / burst)** | `~680 mA @ 5 V` | `~28–45 mA` | **`~1.6 mA` avg (`4.8 mA` radio TX @ 0 dBm)** |
| **Local Voice Prompt Playback** | Linux `mpg123` / `espeak-ng` | Hardware I2S DMA -> MAX98357A | **Hardware EasyDMA I2S -> MAX98357A from onboard 2 MB QSPI Flash** |
| **Voice Storage Budget (6 Phrases)** | Unlimited (SD card, corruptible) | 8 MB QSPI Flash | **2 MB QSPI Flash holds ~65 s of 16 kHz 4-bit IMA-ADPCM (`64 kbps` = `8 KB/s`; all 6 ElevenLabs phrases total `~24 s` = `192 KB`, `< 10%` of flash!)** |
| **Outbox Storage (`MinuteRecord` + `EventRecord`)** | SQLite on SD card | LittleFS / NVS ring | **1.5 MB QSPI circular journal = `> 7,500` records (`> 5.2 days` offline minute + event buffer)** |
| **Boot Time & Brownout Safety** | `~25 s` boot; filesystem corruption risk | `< 300 ms`; atomic flash pages | **`< 80 ms` instant-on; CRC-framed append-only flash ring** |
| **Estimated Runtime on 1× 18650 (`3500 mAh`)** | `~3.8 h` (`11.2 h` on 215 g 10 Ah bank) | `~165 h` (`~6.9 days`) | **`~1,608 h` (`~67 days` / `> 2 months` per charge!) `[CAD/ANALYTICAL]`** |

**Engineering Selection**: **Seeed XIAO nRF52840** (`21.0 × 17.8 mm`) mounted on a `24.0 × 58.0 mm` carrier PCB. Its Cortex-M4F FPU executes the exact exponential gravity/dynamic filters and tilt dot-product of [`pi/detector.py`](../pi/detector.py) (`100 Hz` = `< 0.4%` CPU duty cycle), plays pre-generated 16 kHz IMA-ADPCM ElevenLabs voice clips over hardware `EasyDMA I2S` with zero CPU stutter, and achieves **~9.7× longer battery life than ESP32-S3** and **~143× longer runtime per Wh than Raspberry Pi 4B**.

### 3.2 Rigidly Keyed Inertial Sensor (`TDK ICM-42688-P` vs `LIS3DH`)
- **Selected Sensor**: **TDK InvenSense ICM-42688-P** (6-axis MEMS IMU, `±16 g` accel + `±2000 dps` gyro, ultra-low `70 µg/√Hz` noise density, `< 0.2°` temperature cross-axis stability, 2 KB hardware FIFO + wake-on-motion interrupt; `0.88 mA` in 6-axis LN mode or **`0.28 mA` in 3-axis accelerometer LP/LN 100 Hz mode**; LIS3DH retained as drop-in secondary footprint).
- **Mechanical Anti-Rattle Mounting**: Housed in a dedicated **4-wall precision locating pocket** (`14.8 × 12.8 mm`) molded directly onto the rigid `2.8 mm` front spine wall at `z = 711.2 mm`, secured with M2 hardware + viscoelastic threadlock so sensor rattle is physically eliminated.
- **Clean Coordinate Mapping**: Mounted with IC package axes strictly aligned to global cane axes (`+Z_imu = +Z_cane` shaft upright, `+X_imu = +X_cane` walking forward, `+Y_imu = +Y_cane` lateral left), preserving 1:1 compatibility with `CaneDetector(up=(0, 0, 1))` in [`pi/detector.py`](../pi/detector.py) and `FallFSM` in [`cane/canesense/fsm.py`](../cane/canesense/fsm.py).

### 3.3 Floor-Safe Sealed Voice-Prompt Acoustic Subsystem
- **Driver & Amplifier**: **Analog Devices MAX98357A** filterless I2S Class-D amplifier (`3.2 W` peak into `4 Ω` / `1.8 W` into `8 Ω`, `92%` efficiency, `0.6 µA` hardware `SD_MODE` shutdown) driving a **CUI Devices CMS-28588N-L152** (`Ø28.0 × 5.1 mm`, `8 Ω`, `1.0 W` nominal, IP67 mylar cone, `86 dB @ 0.1 m / 0.1 W` datasheet sensitivity `[CAD/ANALYTICAL]`; mounted speech intelligibility SPL `[PHYSICAL-PENDING]`).
- **Acoustic Baffle & Multi-Axis Venting**:
  - A solid `2.0 mm` internal horizontal baffle at `z = 720.5 mm` isolates a **`~4.6 cm³` rear acoustic back-volume** behind the speaker cone, preventing front-to-back acoustic short-circuiting across the `500–3,500 Hz` human speech band.
  - Because an offset cane lying flat on the floor naturally rolls onto its **`+Y` or `-Y` lateral cheek**, `pod_front_shell` feeds a `1.2 mm` front acoustic plenum into **11 total ports**: **5 forward (`+X`) louvre slots** plus **6 bilateral (`±Y`) corner-cheek slots** (`3` left, `3` right). Regardless of whether the fallen cane lands face-down, face-up, left-side-down, or right-side-down on carpet, at least **7 of 11 acoustic ports** remain completely unobstructed `[CAD/ANALYTICAL]`.

### 3.4 Power Management, Protection & Fuel-Gauge Budget
- **Cell**: Single protected button-top **18650 Li-ion cell** (`Ø18.6 × 69.0 mm`, `3,500 mAh / 12.6 Wh`, integrated DW01/MOSFET over-charge, over-discharge, and short-circuit protection) cradled concentrically at `x = -24.5 mm`.
- **Charger & Power-Path**: **Texas Instruments BQ24074** USB-C linear charger with dynamic power-path management (`I_chg = 1.0 A` -> full `0–100%` charge in `~3.8 hours`; system runs cleanly off VBUS while charging).
- **Fuel Gauge**: **Analog Devices / Maxim MAX17048** (`3 µA` active I2C ModelGauge SoC sensor), adding `battery_pct` and `charging` fields to `INFO` without breaking existing `mobile/PROTOCOL.md` parsers.

#### Daily Average Power Budget (`[CAD/ANALYTICAL]` from IC Datasheets)

| Subsystem / Operating State | Duty Cycle (24 h Day) | Active Current @ 3.7 V | Weighted Avg Current | Notes / Datasheet Basis |
|---|---|---|---|---|
| **nRF52840 System-ON + RTC + BLE Adv/Conn** | 100% (4 h walking + 20 h idle/parked) | `1.15 mA` (conn) / `0.35 mA` (adv) | **`0.55 mA`** | `1 s` adv interval when idle; `75 ms` conn interval during sync bursts |
| **ICM-42688-P Accel @ 100 Hz FIFO** | 100% (or WoM `25 µA` when parked > 10 min) | `0.28 mA` (continuous 100 Hz) | **`0.28 mA`** | Continuous 100 Hz 3-axis accelerometer mode (zero missed strikes) |
| **QSPI Flash Minute/Event Logging + Sync** | `< 0.5%` (`1,440` writes/day + BLE pulls) | `8.5 mA` during write | **`0.04 mA`** | Append-only 256-byte page writes |
| **MAX98357A + Ø28 mm Speaker (Voice/Beeps)** | `0.20%` (`~3 min/day` prompts/chirps @ `0.45 W`) | `125 mA` (`0.6 µA` shutdown) | **`0.25 mA`** | Hardware `/SD` pin held low `99.8%` of day (`0.6 µA`) |
| **BQ24074 + MAX17048 + LDO Quiescent + Divider** | 100% | `0.08 mA` | **`0.08 mA`** | `MAX17048` `3 µA` + `TPS62740` / LDO `I_q` + pull-ups |
| **Conservative Margin (BLE retries, temp, LED)** | — | — | **`0.65 mA`** | `+54%` engineering contingency margin |
| **Total Continuous Average Current** | **24 h / day** | — | **`1.85 mA` (`6.85 mW`)** | Usable capacity (`85%` of `3,500 mAh` = `2,975 mAh`) -> **`1,608 h` (`67.0 days`)** |

### 3.5 BLE 5.3 GATT Compatibility with `mobile/PROTOCOL.md` & `BleCaneTransport.ts`
To drop directly into [`mobile/src/comm/BleCaneTransport.ts`](../mobile/src/comm/BleCaneTransport.ts) without changing `mobile/src/sync/` (`MASTER.md §7.6`), the nRF52840 exposes Service UUID `6E400001-HC02-4A91-B1E0-48414E445943`:
1. **`info` (`...0002`, Read)**: UTF-8 JSON matching `GET /info` (`device_id`, `fw_version`, `last_seq`, `unsynced_count`, `sensor_model: "ICM-42688-P"`, plus optional `battery_pct`).
2. **`time_sync` (`...0003`, Write)**: `int64` `phone_utc_ms`, anchoring `boot_id` offset in non-volatile flash and upgrading current-boot `unsynced` records to `corrected` (identical to `POST /time`).
3. **`control` (`...0004`, Write)**: Framed JSON commands `{"op":"pull","after_seq":N,"limit":K}`, `{"op":"ack","up_to_seq":N}`, and `{"op":"live","on":true}`.
4. **`data` (`...0005`, Notify)**: `[msg_id:u16][chunk_idx:u16][chunk_count:u16][utf8_json_slice...]` (negotiated `MTU = 247 B` -> `238 B` payload/packet; reassembles exact `PullPage` JSON).
5. **`alert` (`...0006`, Notify)**: Immediate push notification of resolved `CaneEventRecord` (`potential_fall` / `help_request`) to `BleCaneTransport.onAlert()`.
6. **`live` (`...0007`, Notify, `1 Hz` when subscribed)**: Pushes `{"ts","mag","dyn","state","strikes_last_10s"}` matching `GET /live` on `review/integration-plus-dev-clean`.

### 3.6 Complete Bill of Materials (BOM) & Unit Cost Estimate

| # | Subsystem | Part / Real MPN | Supplier | Qty | Mass (g) | Envelope (mm) | 1-Unit USD | 100-Unit USD |
|---|---|---|---|---|---|---|---|---|
| 1 | MCU + BLE 5.3 | Seeed Studio XIAO nRF52840 (`102010448`) | DigiKey / Seeed | 1 | 2.4 | `21.0 × 17.8 × 4.2` | $9.90 | $7.90 |
| 2 | 6-Axis IMU | TDK InvenSense `ICM-42688-P` + carrier PCB | DigiKey `1428-ICM-42688-PCT-ND` | 1 | 1.4 | `14.0 × 12.0 × 2.2` | $4.85 | $2.65 |
| 3 | Class-D I2S Amp | Analog Devices `MAX98357AETE+T` | DigiKey | 1 | 0.5 | `3 × 3` QFN (on PCB) | $2.95 | $1.55 |
| 4 | Charger / Path | Texas Instruments `BQ24074RGTR` | DigiKey `296-26458-1-ND` | 1 | 0.4 | `3 × 3` QFN (on PCB) | $2.40 | $1.15 |
| 5 | Li+ Fuel Gauge | Analog/Maxim `MAX17048G+T10` | DigiKey | 1 | 0.2 | `2 × 2` TDFN (on PCB) | $2.75 | $1.40 |
| 6 | Carrier PCB + Passives | Custom 2-Layer FR-4 (`24 × 50 × 1.6 mm`) + USB-C `GCT USB4105` + JST-PH | JLCPCB / DigiKey | 1 | 11.5 | `24.0 × 50.0 × 4.8` | $4.50 | $1.35 |
| 7 | IP67 Micro-Speaker | CUI Devices `CMS-28588N-L152` (`8 Ω, 1 W`, IP67 front) | DigiKey `102-4158-ND` | 1 | 9.2 | `Ø28.0 × 5.1` | $4.15 | $2.60 |
| 8 | Tactile Switch + Lead | Omron `B3FS-4002P` / Wurth `434153025816` IP67 + 22 cm silicone pair | DigiKey | 1 | 1.1 | `12.0 × 12.0 × 4.3` | $2.10 | $1.05 |
| 9 | Protected 18650 Cell | Keeppower `P1835J` (`3500 mAh / 12.6 Wh`, UL1642/UN38.3 cell + PCM) | Illumn / Distribut. | 1 | 48.5 | `Ø18.6 × 69.0` | $9.50 | $5.80 |
| 10 | Printed Housing Set | `grip_upper`, `grip_lower`, `sos_button_cap`, `pod_front`, `pod_rear` (ASA/PETG) | In-house FDM / MJF | 5 pcs | 145.6 | `3-wall + 25% gyroid` | $4.20 | $2.80 |
| 11 | Elastomer Seals | `epdm_shaft_liner` + `usbc_dust_plug` + `Ø1 mm` silicone cord | McMaster / TPU | 1 set | 7.4 | Shore 60A–85A | $1.80 | $0.75 |
| 12 | Fasteners & Inserts | `4× M3×14` + `4× M3×20` Alloy Steel SHCS + `8× M3` Brass Heat-Set Inserts | McMaster `91290A` / `94180A331` | 16 pcs | 11.4 | M3 metric | $2.40 | $0.85 |
| **Sub** | **Smart Kit Total** | **Complete HandyCane v2 Kit (`218.2 g` net replacing `22 g` stock grip)** | — | — | **`240.2 g`** | — | **$51.50** | **$29.85** |
| 13 | Structural Base Cane | Offset Swan-Neck 6061-T6 Aluminum Cane (`Ø22 × 2.0 mm` heavy-wall shaft + ISO rubber tip) | Medical Supply | 1 | `370.3 g` | `910 mm` adjustable | $21.50 | $11.50 |
| **Total** | **Complete Product** | **Ready-to-Walk HandyCane v2 Assistive Cane** | — | — | **`564.0 g`** | `910 × 173 × 47 mm` | **$73.00** | **$41.35** |

---

## 4. Structural & Form-Factor Trade Study + Quantitative Physics

### 4.1 Architecture Trade Study: Integrated Handle/Spine vs Split-Clamshell Collar

| Criterion | Architecture A: Pure Monolithic Smart Handle (Polymer Neck) | Architecture B: Shaft-Only Split-Clamshell Collar (Stock Foam Grip) | **Selected v2 Hybrid: Continuous-Metal Over-Core Ergonomic Grip + Concentric Split-Clamshell Spine** |
|---|---|---|---|
| **Primary Axial Load Safety (`>= 1000 N`)** | **REJECT**: Any polymer joint in the swan-neck or handle core risks brittle creep/layer-delamination fracture under fall arrest loads. | High (stock metal cane untouched), **but** retains poor Ø31 mm cylindrical foam ergonomics and external button cable zip ties. | **BEST OF BOTH**: Continuous, unbroken `Ø22.0 × 2.0 mm` 6061-T6 aluminum tube runs all the way through the swan-neck AND horizontal handle core (`0` holes drilled); contoured shells clamp *over* the metal core in pure compression (`0.41 MPa` @ `1,000 N`). |
| **Hand Ergonomics & Guarded SOS UI** | Excellent | Poor (bolt-on saddle adds bulk & snags) | **Excellent**: Integrated `44.4 mm` palm shelf, `46.0 mm` hypothenar flare, internal wire duct, and `2.0 mm` recessed SOS guard bezel with zero top-surface screws. |
| **Retrofit & Field Serviceability** | Poor (glued/custom tube) | High | **High**: Non-destructive captive `M3` brass heat-set inserts + slotted `EPDM` compression liner clamps onto standard `22 mm` (`19–22.2 mm` parametric) offset canes in `< 3 minutes` with one `2.5 mm` hex key. |
| **Swing Inertia & Fore-Aft Balance** | High | Moderate | **Optimal**: Concentric spine sits immediately beneath the swan-neck (`z = 644–752 mm`, `r_wrist = 188 mm`) with `-X` 18650 cell balancing `+X` PCB/speaker (`Pod CoM_x = -2.51 mm`). |

### 4.2 Quantitative Mass, CoM & Rotational Inertia Comparison (`[CAD/ANALYTICAL]`)
Computed directly by [`hardware/cad_v2/verify_cad_v2.py`](../hardware/cad_v2/verify_cad_v2.py) from the exact B-Rep solids and v1 STL meshes (`I = Σ m_i r_i²` about wrist grip pivot `(18, 0, 886) mm` and shoulder pivot `(18, 0, 1536) mm`):

| Metric (`[CAD/ANALYTICAL]`) | v1 Hackathon Trays (`pi_case` + `bank_holder`) | v2 Engineered Redesign (`cad_v2`) | Verified Improvement |
|---|---|---|---|
| **Net Added Mass Over Stock Cane** | `460.8 g` | **`218.2 g`** (`240.2 g` gross kit minus `22 g` stock grip) | **`−52.6%` net (`−47.9%` gross kit mass)** |
| **Shaft Module Horizontal Eccentricity (`CoM_x`)** | `+20.78 mm` (100% cantilevered forward) | **`−2.51 mm`** (concentrically balanced) | **`18.27 mm` closer to shaft neutral axis (`8.3×` less off-axis torque)** |
| **Shaft Enclosure Width × Vertical Span** | `69.8 mm × 370.6 mm` | **`44.0 mm × 108.0 mm`** | **`−37.0%` narrower, `−70.9%` shorter snag zone** |
| **Added Rotational Inertia About Wrist (`I_wrist`)** | `75,859.0 kg·mm²` (`0.07586 kg·m²`) | **`6,173.0 kg·mm²` (`0.00617 kg·m²`)** | **`−91.9%` (`12.3×` lower wrist swing inertia!)** |
| **Added Rotational Inertia About Shoulder (`I_shoulder`)** | `506,019.0 kg·mm²` (`0.5060 kg·m²`) | **`149,886.0 kg·mm²` (`0.1499 kg·m²`)** | **`−70.4%` (`3.4×` lower whole-arm swing inertia)** |
| **Boolean Solid-to-Solid Interference (120 Pairs)** | Unverified (`IP00` open trays) | **`0.0000 mm³`** (all 16 solids & 16 fastener bodies) | **100% verified non-interfering B-Rep assembly** |

### 4.3 Analytical Structural & Clamping Sanity Summary (`[CAD/ANALYTICAL]`)
1. **Straight Aluminum Shaft Combined Stress (`F = 1,000 N` ISO 11334-4 Static Load)**:
   - Tube `Ø22.0 × 2.0 mm` 6061-T6: `A = 125.66 mm²`, `Z = 576.91 mm³`. With palmar load eccentricity `e <= 15 mm`, combined axial + bending stress in the straight shaft is **`34.0 MPa`** (`~12%` of the `276 MPa` yield strength).
2. **Swan-Neck Bend (governing section)**: Treating the cane as a two-force member, the `1,000 N` load acts along the line from the ferrule tip to the palm load point (`x = 18 mm`). The rearmost point of the bend (`x = -66 mm, z = 853 mm`) sits **`83.3 mm`** off that line. Including the ASME B31.3 in-plane bend stress intensification for an ovalizing thin-wall tube (`i = 0.9 / h^(2/3) = 1.16`), peak stress is **`176 MPa`**, a **static safety factor of `1.57`** on yield. The model is conservative because it ignores the hand's counter-moment.
   - **Design change from this check**: the original `Ø22.0 × 1.6 mm` wall gave `246 MPa` (SF `1.12`) and failed the `SF >= 1.5` criterion, so the wall was increased to `2.0 mm`. Alternatives considered: `7075-T6` at `1.6 mm` (SF `2.04`, but 7075 cannot be cold-bent in T6 temper and needs bend-then-heat-treat), or reducing the swan-neck bow (fixes the root cause, but changes grip ergonomics).
   - **Cost of the change**: the heavier tube adds `46.5 g` to the base cane (`323.8 g` to `370.3 g`). That mass is not in the smart-hardware "added mass" figures in Section 4.2; counted against a stock `1.6 mm` cane, v2 adds `264.7 g` vs v1's `460.8 g` (`-42.6%` instead of `-52.6%`).
   - Fatigue at the bend (`6061-T6` has no endurance limit) and the static proof itself remain `[PHYSICAL-PENDING]` on an ISO 11334-4 test frame.
3. **Column Buckling (`P_cr`)**: Conservative pinned-pinned Euler buckling of the `886 mm` column using the narrower `Ø19.0 × 1.5 mm` lower shaft section gives **`P_cr = 2,755 N`** (`2.75×` the `1,000 N` ISO static requirement).
4. **Ergonomic Polymer Shell Bearing Over Metal Core**: `1,000 N` distributed over `22 × 110 mm = 2,420 mm²` projected aluminum core area produces **`0.41 MPa`** compressive bearing stress (`> 130×` below ASA/PETG `55 MPa` compressive strength).
5. **EPDM + 4× M3 Clamping Slip Margin**: Four `M3×20` SHCS tightened to a polymer-safe `0.55 N·m` (`55%` retained preload after viscoelastic relaxation = `2,017 N` total normal clamp force) across the `μ = 0.55` EPDM sleeve yield **`1,109 N` axial slip resistance** and **`12.2 N·m` torsional anti-rotation capacity**—providing a **`34.4×` safety margin** against a `20 g` ground-strike shock (`32.2 N`) on the `164 g` concentric pod.
