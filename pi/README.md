# Smart cane firmware (Pi device runtime)

Runs on the cane: reads the accelerometer and button, decides what the cane is
doing (walking, dropped, parked), speaks and sends alerts, logs everything to a
local SQLite database. Works fully offline.

## What is where

- `pi/` - the device runtime (runs on the Raspberry Pi, also runs on a laptop for testing)
- `pi/voice_preview.html` - phone test page for the voice clips (see below)
- `firmware/cane_firmware/` - Arduino Uno fallback sketch (sensor + button over serial, no Pi)
- `tests/` - regression suite, simulated inputs only

## Confirmed hardware for this build

- Raspberry Pi (any recent model with Raspberry Pi OS)
- Push button
- Accelerometer: the code auto-detects an ADXL345 (I2C 0x53 or 0x1D) or an
  LIS3DH (I2C 0x18 or 0x19) on bus 1. Confirm the label printed on your board
  before wiring so the wiring guide matches the part you actually have.

Optional, code supports them but they are not required: buzzer, LED, Bluetooth
speaker, Arduino fallback instead of Pi GPIO. The buzzer/LED pins are driven
whether or not anything is attached, so missing attachments cause no errors.

## Test it on a laptop first (no hardware)

The suite replays recorded scenarios through the real detector and reader code.
It never touches the network or audio: the webhook must be unset and alert/voice
calls are recorded by a stub. Verified 10/10 passing on Windows and Linux from a
fresh clone of this branch.

Windows PowerShell, from a fresh clone:

```powershell
cd pi
python -m venv ..\.venv
..\.venv\Scripts\pip install numpy requests
..\.venv\Scripts\python ..\tests\cane_regression_tests.py
```

macOS/Linux: `python3 -m venv ../.venv`, then `../.venv/bin/pip install numpy requests`,
then `../.venv/bin/python ../tests/cane_regression_tests.py`.

Expected: ten PASS lines and exit code 0. Imports resolve from the current
directory, so run it from inside `pi/`, not from the repo root. The suite only
needs numpy and requests; install the full `requirements.txt` when you run the
real reader or recorder.

## Set up the Pi

1. Flash Raspberry Pi OS, boot, connect to Wi-Fi.
2. Enable I2C: `sudo raspi-config` -> Interface Options -> I2C.
3. Copy `pi/` to the Pi, then:

```bash
cd pi
bash pi_setup.sh        # installs system packages, creates .venv, installs requirements
```

4. Wire the accelerometer: VIN to 3V3, GND to GND, SDA to SDA, SCL to SCL
   (confirm your board's label first; the startup log prints which chip and
   address it found). `i2cdetect -y 1` shows the address: `53` or `1d` for an
   ADXL345, `18` or `19` for an LIS3DH.
5. Wire the button to GPIO5 (Grove Base Hat port D5). For a plain button
   between GPIO5 and GND, set `CANE_BUTTON_PULL_UP=1`.
6. First run, with the cane hanging upright and still:

```bash
.venv/bin/python cane_reader.py --calibrate
```

Then start it normally: `.venv/bin/python cane_reader.py`
To start at boot: `sudo cp cane.service /etc/systemd/system/ && sudo systemctl enable --now cane`

## Voice clips (ElevenLabs or any recording)

If a file `voice/<key>.mp3` (or `.wav`) exists, the cane plays it; otherwise it
falls back to espeak-ng on the Pi. The six keys (text in `config.py` under
`PHRASES`):

`dropped`, `ask_ok`, `help`, `cancelled`, `sos`, `sit`

To use ElevenLabs voices: generate the six phrases, download the mp3s, name
them `voice/help.mp3` etc. on the Pi. No API key or code change needed - the
cane only plays the files. Generating clips uses the ElevenLabs account's own
credits.

### Test the clips on a phone

The cane's feed server is safe by default: it binds to this Pi only. For phone
testing on a Wi-Fi network you trust:

```bash
cd pi
.venv/bin/python cane_server.py --lan
```

It prints a one-time pairing code on the Pi's screen (it changes every restart).
On the phone, open `http://<pi-ip>:8000/voice_preview.html`, tap **Enable audio**
(the iPhone requires one tap before sound can play; keep the page open and in the
foreground), and enter the pairing code when the page asks. Then tap phrases to
play clips, or switch on **Auto-play cane events** so the phone plays a clip when
the cane logs a `cane_down`, `alert` or `flow_cancelled` event.

The feed is read-only: nothing through it can write the database or trigger the
cane. It serves only the page, the event list (sequence, time, type - no details),
the live status and the clips; never the source files or the database. Never
port-forward it, and only use LAN mode on networks you trust.

This checks the voice and wording of the clips and the event flow - not the
cane's final speaker output.

## Alerts

Family alerts go to a Discord webhook. Set it as an environment variable,
never in code:

```bash
export CANE_DISCORD_WEBHOOK="https://discord.com/api/webhooks/..."
```

Unset = no external alerts, everything still works and logs locally.

## Tuning

Detection thresholds live in `config.py` with comments. They are starting
points: record real sessions with `record.py`, then adjust. Every value there
is software configuration, not a measurement of your hardware.

## Not done yet (physical testing)

- Nothing here has run on the physical Pi, button or accelerometer yet.
- Wiring polarity, the accelerometer's actual I2C address, and real-world
  thresholds all need the first hardware session.
- This is an assistive prototype. It is not a medical or safety-certified
  device; do not rely on it as the only way to call for help.
