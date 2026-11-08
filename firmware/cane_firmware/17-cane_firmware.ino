// Smart cane firmware - BioHacks 2026
// Arduino Uno/Seeeduino + Grove Base Shield
// Grove ports: accelerometer -> I2C, button -> D2, step-light LED -> D5, buzzer -> D6
// Streams accelerometer data at 100 Hz and handles the SOS button locally.
// Serial protocol (115200 baud, one message per line):
//   OUT  D,<ms>,<ax_mg>,<ay_mg>,<az_mg>   accelerometer sample in milli-g
//   OUT  E,OK_PRESS | E,SOS_HOLD          button events
//   OUT  I,<text>                         info / errors
//   IN   BEEP,0 (stop) | BEEP,1 (locator) | BEEP,2 (alarm) | BEEP,3 (single chirp)
//   IN   LED,<0-255>                      step-light brightness
//   IN   PING                             -> I,PONG

#include <Wire.h>

const uint8_t PIN_BUTTON = 2;
const uint8_t PIN_LED    = 5;   // PWM
const uint8_t PIN_BUZZER = 6;

const unsigned long SAMPLE_US   = 10000;  // 100 Hz
const unsigned long HOLD_MS     = 2000;   // hold this long for SOS
const unsigned long DEBOUNCE_MS = 30;

enum AccelType { NONE, ADXL345, LIS3DH };
AccelType accel = NONE;
uint8_t accelAddr = 0;

unsigned long nextSample = 0;
// button state
bool btnStable = false, btnLastRead = false, sosSent = false;
unsigned long btnChangedAt = 0, pressStart = 0, lastHoldBeep = 0;
// buzzer pattern
uint8_t beepMode = 0; unsigned long beepT0 = 0;
char cmd[24]; uint8_t cmdLen = 0;

void writeReg(uint8_t addr, uint8_t reg, uint8_t val) {
  Wire.beginTransmission(addr); Wire.write(reg); Wire.write(val); Wire.endTransmission();
}
int readReg(uint8_t addr, uint8_t reg) {
  Wire.beginTransmission(addr); Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return -1;
  if (Wire.requestFrom(addr, (uint8_t)1) != 1) return -1;
  return Wire.read();
}

void detectAccel() {
  // ADXL345 (Grove 3-Axis Digital Accelerometer +/-16g): DEVID 0xE5 at 0x53 or 0x1D
  const uint8_t adxl[2] = {0x53, 0x1D};
  for (uint8_t i = 0; i < 2; i++) {
    if (readReg(adxl[i], 0x00) == 0xE5) {
      accel = ADXL345; accelAddr = adxl[i];
      writeReg(accelAddr, 0x2D, 0x00);  // standby
      writeReg(accelAddr, 0x31, 0x0B);  // full resolution, +/-16 g
      writeReg(accelAddr, 0x2C, 0x0A);  // 100 Hz output rate
      writeReg(accelAddr, 0x2D, 0x08);  // measure
      Serial.println(F("I,ACCEL=ADXL345"));
      return;
    }
  }
  // LIS3DH (Grove 3-Axis Digital Accelerometer LIS3DHTR): WHO_AM_I 0x33 at 0x19 or 0x18
  const uint8_t lis[2] = {0x19, 0x18};
  for (uint8_t i = 0; i < 2; i++) {
    if (readReg(lis[i], 0x0F) == 0x33) {
      accel = LIS3DH; accelAddr = lis[i];
      writeReg(accelAddr, 0x20, 0x57);  // 100 Hz, XYZ on
      writeReg(accelAddr, 0x23, 0x38);  // +/-16 g, high resolution
      Serial.println(F("I,ACCEL=LIS3DH"));
      return;
    }
  }
  Serial.println(F("I,ERR_NO_ACCEL check the I2C cable"));
}

bool readAccel(int &x, int &y, int &z) {
  uint8_t b[6];
  if (accel == ADXL345) {
    Wire.beginTransmission(accelAddr); Wire.write(0x32);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(accelAddr, (uint8_t)6) != 6) return false;
    for (uint8_t i = 0; i < 6; i++) b[i] = Wire.read();
    // full resolution: 3.9 mg per LSB
    x = (int)((int16_t)(b[1] << 8 | b[0]) * 39L / 10);
    y = (int)((int16_t)(b[3] << 8 | b[2]) * 39L / 10);
    z = (int)((int16_t)(b[5] << 8 | b[4]) * 39L / 10);
    return true;
  }
  if (accel == LIS3DH) {
    Wire.beginTransmission(accelAddr); Wire.write(0x28 | 0x80);  // auto-increment
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(accelAddr, (uint8_t)6) != 6) return false;
    for (uint8_t i = 0; i < 6; i++) b[i] = Wire.read();
    // 12-bit left-justified, 12 mg per digit at +/-16 g
    x = ((int16_t)(b[1] << 8 | b[0]) >> 4) * 12;
    y = ((int16_t)(b[3] << 8 | b[2]) >> 4) * 12;
    z = ((int16_t)(b[5] << 8 | b[4]) >> 4) * 12;
    return true;
  }
  return false;
}

void handleButton(unsigned long now) {
  bool r = digitalRead(PIN_BUTTON) == HIGH;           // Grove button reads HIGH when pressed
  if (r != btnLastRead) { btnLastRead = r; btnChangedAt = now; }
  if (now - btnChangedAt < DEBOUNCE_MS || r == btnStable) {
    // held: rising beeps so Alex knows the SOS is counting
    if (btnStable && !sosSent && now - lastHoldBeep >= 500) {
      lastHoldBeep = now;
      unsigned long held = now - pressStart;
      tone(PIN_BUZZER, 800 + held / 2, 60);
    }
    if (btnStable && !sosSent && now - pressStart >= HOLD_MS) {
      sosSent = true;
      Serial.println(F("E,SOS_HOLD"));
      tone(PIN_BUZZER, 2200, 400);
    }
    return;
  }
  btnStable = r;
  if (btnStable) { pressStart = now; lastHoldBeep = now; sosSent = false; }
  else if (!sosSent && now - pressStart >= 50) {
    Serial.println(F("E,OK_PRESS"));
    tone(PIN_BUZZER, 1500, 80);
  }
}

unsigned int buzzFreq = 0;                  // what the pattern is currently playing
void setBuzz(unsigned int f) {
  if (f == buzzFreq) return;
  buzzFreq = f;
  if (f) tone(PIN_BUZZER, f); else noTone(PIN_BUZZER);
}

void handleBeeps(unsigned long now) {
  if (btnStable) { buzzFreq = 0; return; }  // button feedback has priority
  unsigned long t = (now - beepT0) % 1000;
  if (beepMode == 1) setBuzz(t < 150 ? 2000 : 0);          // locator: short beep every second
  else if (beepMode == 2) setBuzz(t < 500 ? 2400 : 1800);  // alarm: two-tone
}

void handleCommand(char *c) {
  if (strncmp(c, "BEEP,", 5) == 0) {
    uint8_t m = atoi(c + 5);
    beepT0 = millis();
    if (m == 3) { tone(PIN_BUZZER, 1800, 120); beepMode = 0; }
    else { beepMode = m; if (m == 0) setBuzz(0); }
  } else if (strncmp(c, "LED,", 4) == 0) {
    analogWrite(PIN_LED, constrain(atoi(c + 4), 0, 255));
  } else if (strcmp(c, "PING") == 0) {
    Serial.println(F("I,PONG"));
  }
}

void readSerial() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (cmdLen) { cmd[cmdLen] = 0; handleCommand(cmd); cmdLen = 0; }
    } else if (cmdLen < sizeof(cmd) - 1) cmd[cmdLen++] = ch;
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_BUTTON, INPUT);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  Wire.begin();
  Wire.setClock(400000);
  delay(50);
  detectAccel();
  tone(PIN_BUZZER, 1500, 100);              // boot chirp
  nextSample = micros();
}

void loop() {
  unsigned long now = millis();
  readSerial();
  handleButton(now);
  handleBeeps(now);
  if ((long)(micros() - nextSample) >= 0) {
    nextSample += SAMPLE_US;
    int x, y, z;
    if (readAccel(x, y, z)) {
      Serial.print(F("D,")); Serial.print(now); Serial.print(',');
      Serial.print(x); Serial.print(','); Serial.print(y); Serial.print(','); Serial.println(z);
    }
  }
}
