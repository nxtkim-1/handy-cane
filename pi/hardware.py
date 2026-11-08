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
        self._stop = threading.Event()           # set by close(): every worker loop exits
        self._threads = []
    def _spawn(self, target, *args):
        if self._stop.is_set():
            return
        t = threading.Thread(target=target, args=args, daemon=True)
        self._threads = [x for x in self._threads if x.is_alive()] + [t]
        t.start()
    def _put(self, s):
        try:
            self.samples.put_nowait(s)
        except queue.Full:                       # never block the sampler; drop the oldest
            self.samples.get_nowait(); self.samples.put_nowait(s)
    def beep(self, mode): pass
    def led(self, level): pass
    def close(self, timeout=2.0):
        self._stop.set()
        me = threading.current_thread()
        for t in list(self._threads):
            if t is not me:
                t.join(timeout)

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
        self._spawn(self._sample_loop)
        self._spawn(self._buzzer_loop)
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
        while not self._stop.is_set():
            try:
                ax, ay, az = self._read()
                self._put((time.time(), ax, ay, az))
            except OSError as e:                  # a loose cable: report it, keep trying
                print("I2C read failed:", e)
                self._stop.wait(0.5)
            nxt += period
            self._stop.wait(max(0.0, nxt - time.perf_counter()))

    # --- button: quick press = I'm OK, hold 2 s = SOS, rising beeps while held ---
    def _pressed(self):
        self.press_t, self.sos_sent = time.time(), False
        self._spawn(self._hold_feedback)
    def _hold_feedback(self):
        while self.button.is_pressed and not self.sos_sent and not self._stop.is_set():
            self._tone(800 + (time.time() - self.press_t) * 500, 0.06)
            self._stop.wait(0.44)
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
        if self._stop.is_set():
            return
        with self._lock:                          # one tone at a time; wait() wakes early on close()
            self.buzzer.frequency = freq
            self.buzzer.value = 0.5
            self._stop.wait(secs)
            self.buzzer.value = 0
    def _buzzer_loop(self):
        while not self._stop.is_set():
            if self.button.is_pressed or self.mode == 0:
                self._stop.wait(0.05); continue
            t = (time.time() - self.mode_t0) % 1.0
            if self.mode == 1:                    # locator
                self._tone(2000, 0.15); self._stop.wait(0.85)
            elif self.mode == 2:                  # alarm, two-tone
                self._tone(2400 if t < 0.5 else 1800, 0.25)
    def beep(self, mode):
        if mode == 3:
            self._spawn(self._tone, 1800, 0.12)
            return
        self.mode, self.mode_t0 = mode, time.time()
    def led(self, level):
        self.light.value = max(0, min(255, level)) / 255
    def close(self, timeout=2.0):
        super().close(timeout)
        for dev in (self.buzzer, self.light, self.button, self.bus):
            try:
                dev.close()
            except Exception:
                pass

# ---------- Arduino + Grove shield on the Pi's USB (cane_firmware.ino) ----------
class SerialCane(_Base):
    def __init__(self):
        super().__init__()
        import serial
        self.port = serial.Serial(C.SERIAL_PORT, C.BAUD, timeout=1)
        time.sleep(2)                             # the Uno resets when the port opens
        self._spawn(self._loop)
    def _loop(self):
        while not self._stop.is_set():
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
    def close(self, timeout=2.0):
        super().close(timeout)                    # readline() times out after 1 s, so the loop exits
        try:
            self.port.close()
        except Exception:
            pass

# ---------- replay a recording (test the software anywhere) ----------
class FakeCane(_Base):
    def __init__(self, path):
        super().__init__()
        self.path = path
        self._spawn(self._loop)
    def _loop(self):
        while not self._stop.is_set():
            with open(self.path) as f:
                for row in csv.DictReader(f):
                    if self._stop.is_set():
                        return
                    self._put((time.time(), float(row["ax"]), float(row["ay"]), float(row["az"])))
                    self._stop.wait(1 / C.SAMPLE_HZ)
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
