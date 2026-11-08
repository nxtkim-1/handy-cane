"""Register a cane in the backend and assign it to a patient (a stand-in for the pairing flow).

    python -m backend.app.register_device cane-sim              # assign to the simulated demo patient
    python -m backend.app.register_device cane-7f3a --patient-id <uuid>

Idempotent. Without this the ingest endpoint rejects uploads from a cane it has never heard of.
"""
from __future__ import annotations

import argparse
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from backend.app import models as m
from backend.app.core.db import SessionLocal, init_db
from backend.app.core.security import hash_secret


def register(db, device_id: str, patient_id: uuid.UUID | None = None, sensor_model: str = "unknown") -> str:
    if patient_id is None:
        p = db.scalars(select(m.Patient).where(m.Patient.is_simulated == True)).first()  # noqa: E712
        if p is None:
            raise SystemExit("No simulated demo patient found. Run: python -m backend.app.seed")
    else:
        p = db.get(m.Patient, patient_id)
        if p is None:
            raise SystemExit(f"No patient {patient_id}")
    dev = db.get(m.Device, device_id)
    if dev is None:
        dev = m.Device(device_id=device_id, sensor_model=sensor_model, fw_version="manual",
                       secret_hash=hash_secret(uuid.uuid4().hex), is_simulated=bool(p.is_simulated))
        db.add(dev)
        db.flush()
    open_assignment = db.scalars(select(m.DeviceAssignment).where(
        m.DeviceAssignment.device_id == device_id, m.DeviceAssignment.patient_id == p.patient_id,
        m.DeviceAssignment.valid_to.is_(None))).first()
    if open_assignment is None:
        db.add(m.DeviceAssignment(device_id=device_id, patient_id=p.patient_id,
                                  valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc)))
    db.commit()
    return f"{device_id} -> {p.display_name} ({p.patient_id})"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("device_id")
    ap.add_argument("--patient-id", type=uuid.UUID, default=None)
    ap.add_argument("--sensor-model", default="unknown")
    a = ap.parse_args()
    init_db()
    with SessionLocal() as db:
        print("registered", register(db, a.device_id, a.patient_id, a.sensor_model))


if __name__ == "__main__":
    main()
