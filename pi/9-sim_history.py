"""Fill 8 weeks of SIMULATED history for the demo (marked simulated=1, shown as such in the app).
Stride variability and stumbles drift up slowly, with more stumbles in the evening."""
import json, random, time
import db

con = db.connect()
con.execute("DELETE FROM events WHERE simulated = 1"); con.execute("DELETE FROM strides WHERE simulated = 1")
random.seed(4)
now = time.time()
for day in range(56, 0, -1):
    base = now - day * 86400
    drift = (56 - day) / 56                       # 0 -> 1 over eight weeks
    for _ in range(600):                           # strides that day
        iv = random.gauss(1.15 + 0.05 * drift, 0.045 + 0.03 * drift)
        con.execute("INSERT INTO strides VALUES (?,?,1)", (base + random.uniform(8, 21) * 3600, round(iv, 3)))
    for _ in range(random.choice([0, 0, 1, 1, 2]) + int(drift * 3)):
        evening = random.random() < 0.6
        hour = random.uniform(18, 21.5) if evening else random.uniform(9, 17)
        con.execute("INSERT INTO events VALUES (?,?,?,1)", (base + hour * 3600, "stumble", json.dumps({"evening": evening})))
    if random.random() < 0.08 + 0.1 * drift:
        con.execute("INSERT INTO events VALUES (?,?,?,1)", (base + 19.5 * 3600, "cane_down", json.dumps({"impact": False})))
con.commit()
print("Simulated history written.")
