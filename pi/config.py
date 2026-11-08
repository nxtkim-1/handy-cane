"""All settings in one place. Edit this file, not the code."""
import os

SERIAL_PORT = os.getenv("CANE_PORT", "/dev/ttyACM0")   # only for SOURCE="serial"; COM3 etc. on Windows
BAUD = 115200

PERSON = "Alex"
FAMILY = ["Jordan", "Maya", "Leo"]
LOCATION_LABEL = "home"                          # used in alert text, e.g. "Room 204" at school

# Discord webhook for family alerts (Server settings > Integrations > Webhooks > Copy URL)
DISCORD_WEBHOOK = os.getenv("CANE_DISCORD_WEBHOOK", "")

# Gemini: key from aistudio.google.com, set as an environment variable, never in code
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

DB_PATH = "data/cane.db"
CALIB_PATH = "data/calibration.json"
EVENT_MODEL_PATH = "models/event_model.joblib"
GAIT_MODEL_PATH = "models/gait_model.joblib"

# Detection thresholds (tune from your own recordings, see the testing section)
STRIKE_G = 0.45          # dynamic acceleration that counts as a cane strike
STRIKE_REFRACTORY_S = 0.35
STRIDE_MIN_S, STRIDE_MAX_S = 0.6, 2.5
STUMBLE_G = 1.4          # sharp jolt while the cane stays upright
IMPACT_G = 2.5           # total acceleration for a hard hit
UPRIGHT_MAX_DEG = 35     # cane counts as upright below this tilt
DOWN_MIN_DEG = 60        # cane counts as lying down above this tilt
STILL_G = 0.05           # below this dynamic acceleration the cane is still
DOWN_CONFIRM_S = 1.5     # lying still this long = down
PICKUP_CONFIRM_S = 1.0

# Drop / fall timeline (seconds after the cane goes down)
ASK_AFTER_S = 30         # "Alex, are you okay?"
ALERT_AFTER_S = 60       # family alert
ASK_AFTER_IMPACT_S = 10  # shorter when a hard impact came first
ALERT_AFTER_IMPACT_S = 30
REPEAT_HELP_S = 20

# Evening mode: his falls were after 6 pm
EVENING_START_H, EVENING_END_H = 18, 7
EVENING_STUMBLE_SCALE = 0.85   # more sensitive in the evening
STEP_LIGHT_LEVEL = 200
STEP_LIGHT_OFF_AFTER_S = 20

# Sunday cooking
STAND_LIMIT_MIN = 25

VOICE_DIR = "voice"
PHRASES = {
    "dropped":   "Your cane is down. It's beeping so you can find it.",
    "ask_ok":    "Alex, are you okay? Press the button if you're fine.",
    "help":      "This is Alex. I've fallen and I can't get up. Please come and help.",
    "cancelled": "Okay. Alert cancelled.",
    "sos":       "Help is being called. Hold on.",
    "sit":       "You've been standing a while. Sit down for the next step?",
}
PARKED_G = 0.015         # quieter than a hand can hold = hung on a desk or leaning; button presses ignored

# ---------- Raspberry Pi hardware ----------
# SOURCE: "gpio"  = Grove modules wired straight to the Pi (Grove Base Hat or jumper wires)
#         "serial" = Arduino + Grove shield plugged into the Pi by USB, running cane_firmware.ino
#         "fake:<csv>" = replay a recording, for testing on any computer
SOURCE = os.getenv("CANE_SOURCE", "gpio")
I2C_BUS = 1
PIN_BUTTON = 5      # BCM numbering. Grove Base Hat port D5
BUTTON_PULL_UP = os.getenv("CANE_BUTTON_PULL_UP", "0") == "1"  # 1 = plain push button wired GPIO5 -> GND
PIN_BUZZER = 12     # Grove Base Hat port PWM
PIN_LED = 16        # Grove Base Hat port D16
SAMPLE_HZ = 100

# ---------- phone sync outbox (link.py / link_server.py) ----------
DEVICE_ID = os.getenv("CANE_DEVICE_ID", "cane-dev")
LINK_DB_PATH = os.getenv("CANE_LINK_DB", os.path.join(os.path.dirname(DB_PATH), "outbox.db"))
LINK_PORT = int(os.getenv("CANE_LINK_PORT", "8765"))
FW_VERSION = "0.4.0"
