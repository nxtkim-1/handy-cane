"""One interface for the cane's hardware, whatever it's wired to.
   hw = hardware.open_cane()
   hw.samples  -> queue of (t, ax, ay, az) in seconds and g, 100 per second
   hw.events   -> queue of "OK_PRESS" / "SOS_HOLD"
   hw.beep(0|1|2|3)  stop / locator / alarm / chirp       hw.led(0-255)  step light"""
import csv, queue, threading, time
import config as C

class _Base:
    def __init__(self):
        self.samples = queue.Queue(maxsize=3000)
        self.events = queue.Queue()
    def _put(self, s):
        try:
            self.samples.put_nowait(s)
        except queue.Full:                       # never block the sampler; drop the oldest
            self.samples.get_nowait(); self.samples.put_nowait(s)
    def beep(self, mode): pass
    def led(self, level): pass
    def close(self): pass

# ---------- Grove modules wired straight to the Pi ----------
class PiCane(_Base):
    def __init__(self):
        super().__init__()
        from smbus2 import SMBus
        from gpiozero import Button, PWMOutputDevice, PWMLED
        self.bus = SMBus(C.I2C_BUS)
        self.kind, self.addr = self._detect()
        print("Accelerometer:", self.kind, hex(self.addr))
        if C.BUTTON_PULL_UP:      # plain push button between GPIO 5 and GND, Pi's internal pull-up
            self.button = Button(C.PIN_BUTTON, pull_up=True, bounce_time=0.03, hold_time=2.0)
        else:                     # Grove button drives its signal HIGH when pressed, has its own pull-down
            self.button = Button(C.PIN_BUTTON, pull_up=None, active_state=True, bounce_time=0.03, hold_time=2.0)
        self.button.when_pressed = self._pressed
        self.button.when_held = self._held
        self.button.when_released = self._released
        self.buzzer = PWMOutputDevice(C.PIN_BUZZER, initial_value=0, frequency=2000)
        self.light = PWMLED(C.PIN_LED)
        self.mode, self.mode_t0, self.press_t, self.sos_sent = 0, time.time(), None, False
        self._lock = threading.Lock()
        threading.Thread(target=self._sample_loop, daemon=True).start()
        threading.Thread(target=self._buzzer_loop, daemon=True).start()
        self._tone(1500, 0.1)                     # boot chirp

    def _detect(self):
        for addr in (0x53, 0x1D):                 # ADXL345
            try:
                if self.bus.read_byte_data(addr, 0x00) == 0xE5:
                    self.bus.write_byte_data(addr, 0x2D, 0x00)
                    self.bus.write_byte_data(addr, 0x31, 0x0B)   # full resolution, +/-16 g
                    self.bus.write_byte_data(addr, 0x2C, 0x0A)   # 100 Hz
                    self.bus.write_byte_data(addr, 0x2D, 0x08)   # measure
                    return "ADXL345", addr
            except OSError:
                pass
        for addr in (0x19, 0x18):                 # LIS3DH
            try:
                if self.bus.read_byte_data(addr, 0x0F) == 0x33:
                    self.bus.write_byte_data(addr, 0x20, 0x57)   # 100 Hz, XYZ on
                    self.bus.write_byte_data(addr, 0x23, 0x38)   # +/-16 g, high resolution
                    return "LIS3DH", addr
            except OSError:
                pass
        raise RuntimeError("No accelerometer found on I2C. Run 'i2cdetect -y 1' and check the cable.")

    def _read(self):
        if self.kind == "ADXL345":
            b = self.bus.read_i2c_block_data(self.addr, 0x32, 6)
            conv = lambda lo, hi: int.from_bytes(bytes([lo, hi]), "little", signed=True) * 0.0039
        else:
            b = self.bus.read_i2c_block_data(self.addr, 0x28 | 0x80, 6)
            conv = lambda lo, hi: (int.from_bytes(bytes([lo, hi]), "little", signed=True) >> 4) * 0.012
        return conv(b[0], b[1]), conv(b[2], b[3]), conv(b[4], b[5])

    def _sample_loop(self):
        period, nxt = 1 / C.SAMPLE_HZ, time.perf_counter()
        while True:
            try:
                ax, ay, az = self._read()
                self._put((time.time(), ax, ay, az))
            except OSError as e:                  # a loose cable: report it, keep trying
                print("I2C read failed:", e)
                time.sleep(0.5)
            nxt += period
            time.sleep(max(0.0, nxt - time.perf_counter()))

    # --- button: quick press = I'm OK, hold 2 s = SOS, rising beeps while held ---
    def _pressed(self):
        self.press_t, self.sos_sent = time.time(), False
        threading.Thread(target=self._hold_feedback, daemon=True).start()
    def _hold_feedback(self):
        while self.button.is_pressed and not self.sos_sent:
            self._tone(800 + (time.time() - self.press_t) * 500, 0.06)
            time.sleep(0.44)
    def _held(self):
        self.sos_sent = True
        self.events.put("SOS_HOLD")
        self._tone(2200, 0.4)
    def _released(self):
        if not self.sos_sent and self.press_t and time.time() - self.press_t >= 0.05:
            self.events.put("OK_PRESS")
            self._tone(1500, 0.08)

    # --- buzzer and light ---
    def _tone(self, freq, secs):
        with self._lock:
            self.buzzer.frequency = freq
            self.buzzer.value = 0.5
            time.sleep(secs)
            self.buzzer.value = 0
    def _buzzer_loop(self):
        while True:
            if self.button.is_pressed or self.mode == 0:
                time.sleep(0.05); continue
            t = (time.time() - self.mode_t0) % 1.0
            if self.mode == 1:                    # locator
                self._tone(2000, 0.15); time.sleep(0.85)
            elif self.mode == 2:                  # alarm, two-tone
                self._tone(2400 if t < 0.5 else 1800, 0.25)
    def beep(self, mode):
        if mode == 3:
            threading.Thread(target=self._tone, args=(1800, 0.12), daemon=True).start()
            return
        self.mode, self.mode_t0 = mode, time.time()
    def led(self, level):
        self.light.value = max(0, min(255, level)) / 255

# ---------- Arduino + Grove shield on the Pi's USB (cane_firmware.ino) ----------
class SerialCane(_Base):
    def __init__(self):
        super().__init__()
        import serial
        self.port = serial.Serial(C.SERIAL_PORT, C.BAUD, timeout=1)
        time.sleep(2)                             # the Uno resets when the port opens
        threading.Thread(target=self._loop, daemon=True).start()
    def _loop(self):
        while True:
            line = self.port.readline().decode(errors="ignore").strip()
            if line.startswith("D,"):
                try:
                    _, _, x, y, z = line.split(",")
                    self._put((time.time(), int(x) / 1000, int(y) / 1000, int(z) / 1000))
                except ValueError:
                    pass
            elif line.startswith("E,"):
                self.events.put(line[2:])
            elif line.startswith("I,"):
                print("cane:", line[2:])
    def beep(self, mode):
        self.port.write(f"BEEP,{mode}\n".encode())
    def led(self, level):
        self.port.write(f"LED,{int(level)}\n".encode())

# ---------- replay a recording (test the software anywhere) ----------
class FakeCane(_Base):
    def __init__(self, path):
        super().__init__()
        self.path = path
        threading.Thread(target=self._loop, daemon=True).start()
    def _loop(self):
        while True:
            with open(self.path) as f:
                for row in csv.DictReader(f):
                    self._put((time.time(), float(row["ax"]), float(row["ay"]), float(row["az"])))
                    time.sleep(1 / C.SAMPLE_HZ)
    def beep(self, mode): print("[beep]", mode)
    def led(self, level): print("[led]", level)

def open_cane():
    if C.SOURCE == "gpio":
        return PiCane()
    if C.SOURCE == "serial":
        return SerialCane()
    if C.SOURCE.startswith("fake:"):
        return FakeCane(C.SOURCE[5:])
    raise ValueError(f"Unknown CANE_SOURCE {C.SOURCE!r}")
