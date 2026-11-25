# Handy Cane: architecture and decision record

The constraint: the cane asks first and escalates only when nobody answers, and nothing in the system is a medical claim.

## System walk

The Raspberry Pi runtime (pi/) reads the cane's accelerometer and turns the stream into events in pure, hardware-free logic (pi/detector.py). The alert flow speaks first and escalates on a timer that depends on whether an impact was seen. Voice prompts play on the cane, family alerts go to a webhook on a background thread, and everything also flows to the FastAPI backend (backend/), which stores events, alerts and reports and computes a triage ordering. The Expo app (mobile/) pulls from the backend for three roles; the bridge and simulator (cane/) replay recorded sessions for tests.

## Decision records

### D1. Ask, then escalate, on impact-based timing

- Problem: a fall detector that screams on every drop trains people to ignore it; one that never alerts is useless.
- Choice: the cane speaks "Are you okay?" and waits. After an impact it asks at 10 s and alerts at 30 s; with no impact (a slow slide down), at 30 s and 60 s. A button press cancels. A stumble is logged with peak g-force and never alarms. A 2-second hold is an explicit SOS (README).
- Not yet measured: detection performance on real human falls; behavior so far is exercised against simulated and recorded sessions (README status).

### D2. Pure detector logic, no hardware in the loop

- Choice: pi/detector.py is written as pure logic ("no hardware, easy to test", module docstring): gravity is estimated with a slow exponential average, dynamic motion with a faster one, and tilt against the calibrated upright vector drives the down/parked/pickup states.
- Evidence: regression tests with recorded fixtures (tests/, README status: 16 regression tests passing on the reviewed branch).

### D3. Alerts never block the cane

- Choice: family alerts POST to a Discord webhook from a daemon thread with a 5-second timeout, so a slow network never delays the next sensor read or voice prompt (pi/alerts.py). With no webhook configured, the alert is printed, not lost silently.
- Limits: webhook delivery itself is best-effort; failures are logged to the console.

### D4. Severity is triage, not diagnosis

- Choice: the backend orders alerts high/medium/low from the event facts (what happened, whether anyone answered, impact strength), and the README states in the same breath that this is a prioritization heuristic, not a medical or clinical assessment.
- Limits: the whole project carries the same line: nothing here is a medical device or a clinical claim.

### D5. Caregiver access is consent-gated

- Choice: the cane user's data is visible to caregivers only with the patient's consent; clinicians get their own view. The patient sees their own activity against their own baseline rather than a population norm (README).

### D6. Demo mode first on mobile

- Choice: the Expo app runs end to end with no backend (mock API, demo accounts), with the live mode behind an explicit URL setting; the cane wire format is a documented file (mobile/PROTOCOL.md, mobile/README.md).
- Evidence: 152 mobile tests and a clean type-check on the reviewed branch (README status); pure chart logic ("no-data-is-not-zero") is separated for testing.

## Interview questions this doc should let the owner answer

- The webhook endpoint hangs for 30 seconds. What does the cane user experience in those 30 seconds?
- Why does a stumble never alarm, and where is that decision made in code?
- A caregiver opens the app without patient consent. What do they see, and what enforces it?
