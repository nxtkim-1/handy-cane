# Handy Cane

An assistive smart cane: sensors on the cane detect when it goes down or is dropped, the cane asks the user out loud if they are okay, and if nobody answers it raises an alert for caregivers. A companion app serves the cane user, their caregivers, and clinicians.

## What it does

- **Cane-down detection** from the cane's accelerometer (LIS3DH): cane down after an impact, cane down with no impact, and pickup when the cane is lifted again.
- **Stumble detection**: a sharp jolt where the cane stays upright - logged with peak g-force, no alarm.
- **Parked detection**: when the cane is hung up or leaning still, bumps are ignored.
- **Ask, then escalate**: on a possible fall the cane speaks "Are you okay? Press the button if you are fine." A short button press cancels. No answer escalates to a caregiver alert. Timing is impact-based: after an impact the cane asks at 10s and alerts at 30s; with no impact it asks at 30s and alerts at 60s.
- **SOS button**: hold the cane button for 2 seconds to trigger an SOS alert.
- **Voice prompts**: pre-generated ElevenLabs speech on the cane, with an espeak fallback and a paired phone as an optional speaker.
- **Companion app**: the patient sees cane-active time against their own baseline, alerts, and trend reports. Caregivers and clinicians see a patient list with priority badges and per-patient overview, trends, alerts, and reports. Caregiver access is consent-gated by the patient.
- **Alert severity for triage**: high / medium / low ordering so a caregiver knows what to look at first.

Severity is a prioritization heuristic computed from the event (what happened, whether anyone answered, impact strength). It is not a medical or clinical assessment.

## Repository layout

- `pi/` - Raspberry Pi cane runtime: detector, alert flow, voice prompts, phone web page, REST API and live event feed
- `cane/` - CaneLink bridge and cane sensing libraries, with a simulator (`run_sim.py`)
- `backend/` - FastAPI backend: events, alerts, reports, severity ordering
- `mobile/` - Expo / React Native companion app (patient, caregiver, clinician)
- `firmware/`, `hardware/`, `interface/`, `app/` - original planning notes and scaffolds
- `tools/` - session recording and evaluation utilities
- `tests/` - cane regression tests and fixtures
- `docs/` - setup, deployment, and data-collection notes

## Status

Current build state. On the reviewed branch `review/integration-plus-dev-clean`: 122 backend tests, 152 mobile tests, and 16 regression tests pass, and the mobile app type-checks cleanly.

Fall and drop behavior has been exercised against simulated and recorded sensor sessions. Detection performance on real human falls has not been validated, and nothing in this project is a medical device or a clinical claim.
