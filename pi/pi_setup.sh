#!/bin/bash
# One-time setup on the Raspberry Pi (Raspberry Pi OS Bookworm, 64-bit, with desktop).
# Run from the project folder:  bash pi_setup.sh
set -e
sudo apt update
sudo apt install -y python3-venv python3-gpiozero python3-lgpio i2c-tools espeak-ng mpg123
sudo raspi-config nonint do_i2c 0                 # turn on I2C
python3 -m venv --system-site-packages .venv      # system packages give the venv gpiozero + lgpio
.venv/bin/pip install --upgrade pip
.venv/bin/pip install smbus2 pyserial numpy pandas scikit-learn joblib streamlit requests google-genai pydantic
mkdir -p data/raw models voice
[ -f .env ] || cp env.example .env
mkdir -p ~/.config/systemd/user
sed "s|__DIR__|$PWD|g" cane.service > ~/.config/systemd/user/cane.service
sed "s|__DIR__|$PWD|g" cane-dashboard.service > ~/.config/systemd/user/cane-dashboard.service
loginctl enable-linger "$USER"                    # user services start at boot, with Bluetooth audio
systemctl --user daemon-reload
echo
echo "Done. Next: edit .env, pair the speaker, then:"
echo "  .venv/bin/python cane_reader.py --calibrate"
echo "  systemctl --user enable --now cane cane-dashboard"
