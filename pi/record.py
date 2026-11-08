"""Record labelled training data.  Usage:  .venv/bin/python record.py walking
Labels: walking, stumble, dropped, fall, still, hanging, stairs.  Ctrl+C stops.
Each run saves data/raw/<label>_<time>.csv. Record each label several times, with different people.
Stop cane_reader first (systemctl --user stop cane) so only one program uses the sensors."""
import csv, os, sys, time
import hardware

label = sys.argv[1] if len(sys.argv) > 1 else "unlabelled"
os.makedirs("data/raw", exist_ok=True)
path = f"data/raw/{label}_{time.strftime('%H%M%S')}.csv"
hw = hardware.open_cane()
print(f"Recording '{label}' to {path}. Ctrl+C to stop.")
hw.beep(3)
n = 0
with open(path, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["t", "ax", "ay", "az"])
    try:
        while True:
            t, ax, ay, az = hw.samples.get()
            w.writerow([round(t, 3), round(ax, 4), round(ay, 4), round(az, 4)])
            n += 1
            if n % 500 == 0:
                print(f"{n / 100:.0f} s recorded")
    except KeyboardInterrupt:
        pass
hw.beep(3)
print(f"Saved {n} samples ({n / 100:.1f} s).")
