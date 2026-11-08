# Smart cane firmware (Pi device runtime)

Runs on the cane: reads the accelerometer and button, decides what the cane is
doing (walking, dropped, parked), speaks and sends alerts, logs everything to a
local SQLite database. Works fully offline.

## What is where

- `pi/` - the device runtime (runs on the Raspberry Pi, also runs on a laptop for testing)
- `firmware/cane_firmware/` - Arduino Uno fallback sketch (sensor + button over serial, no Pi)
- `tests/` - regression suite, simulated inputs only

## Confirmed hardware for this build

- Raspberry Pi (any recent model with Raspberry Pi OS)
- Push button - GPIO5 (Grove Base Hat port D5), or plain button GPIO5 to GND with `CANE_BUTTON_PULL_UP=1`
- ADXL345 accelerometer - I2C bus 1

Optional, code supports them but they are not required: buzzer (GPIO12),
LED (GPIO16), Bluetooth speaker, Arduino fallback instead of Pi GPIO.

## Test it on a laptop first (no hardware)

The suite replays recorded scenarios through the real detector and reader code.
It never touches the network or audio: the webhook must be unset and alert/voice
calls are recorded by a stub.

Windows PowerShell, from a fresh clone:

```powershell
cd pi
python -m venv ..\.venv
..\.venv\Scripts\pip install -r requirements.txt
..\.venv\Scripts\python ..\tests\cane_regression_tests.py
```

macOS/Linux: same idea, `.venv/bin/python ../tests/cane_regression_tests.py`.

Expected: ten PASS lines and exit code 0. Imports resolve from the current
directory, so run it from inside `pi/`, not from the repo root.

## Set up the Pi

1. Flash Raspberry Pi OS, boot, connect to Wi-Fi.
2. Enable I2C: `sudo raspi-config` -> Interface Options -> I2C.
3. Copy `pi/` to the Pi, then:

```bash
cd pi
bash pi_setup.sh        # installs system packages, creates .venv, installs requirements
```

4. Wire the ADXL345: VIN to 3V3, GND to GND, SDA to SDA, SCL to SCL.
   Check the address: `i2cdetect -y 1` - expect `53` (SDO to GND) or `1d` (SDO to 3V3).
5. Wire the button to GPIO5 and GND.
6. First run, with the cane hanging upright and still:

```bash
.venv/bin/python cane_reader.py --calibrate
```

Then start it normally: `.venv/bin/python cane_reader.py`
To start at boot: `sudo cp cane.service /etc/systemd/system/ && sudo systemctl enable --now cane`

## Voice clips (ElevenLabs or any recording)

If a file `voice/<key>.mp3` (or `.wav`) exists, the cane plays it; otherwise it
falls back to espeak-ng on the Pi. The six keys:

`dropped`, `ask_ok`, `help`, `cancelled`, `sos`, `sit`

To use ElevenLabs voices: generate the six phrases (text is in `config.py`
under `PHRASES`), download the mp3s, name them `voice/help.mp3` etc. on the Pi.
No API key or code change needed - the cane only plays the files. Generating
clips uses the ElevenLabs account's own credits.

To preview the clips on an iPhone before the Pi is involved: open the mp3s in
Safari and tap play. That checks the voice and wording only, not the cane's
final speaker output.

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
