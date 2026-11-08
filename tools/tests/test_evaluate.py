import json
from dataclasses import replace

import numpy as np
import pytest

from cane.canesense.fsm import Config
from tools import evaluate as E
from tools.session import save
from tools.synth_sessions import build_session, make_dataset


def one(label, seed=0, **kw):
    s = build_session([(label, kw)], seed=seed)
    r = E.evaluate([s], with_features=False)
    return r, r["per_label"][label]


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_walking_has_no_false_alarms(seed):
    for kw in (dict(secs=120.0), dict(secs=120.0, slow=True)):
        r, p = one("walk", seed, **kw)
        assert p["episodes"] == 0 and r["false_alarms"]["pre_alerts"] == 0


@pytest.mark.parametrize("label", ["idle", "sit", "lean", "car", "floor_tap", "other"])
def test_other_normal_labels_never_alert(label):
    for seed in range(3):
        _, p = one(label, seed)
        assert p["pre_alerts"] == 0 and p["escalations"] == 0, (label, seed)


def test_floor_tap_triggers_impact_but_recovers():
    _, p = one("floor_tap", 0)
    assert p["episodes"] >= 1 and p["impact_only"] == p["episodes"]


def test_lying_still_fall_sim_is_detected_and_escalates_unattended():
    for seed in range(4):
        r, p = one("fall_sim", seed, press_at_s=None)
        assert r["fall_sim"]["sensitivity"] == 1.0 and p["escalations"] == 1
        assert 10 <= r["fall_sim"]["median_s_trigger_to_pre_alert"] <= 16


def test_soft_fall_detected_via_tilt_even_below_impact_threshold():
    r, _ = one("fall_sim", 5, soft=True, press_at_s=None)
    assert r["fall_sim"]["sensitivity"] == 1.0


def test_fall_with_button_press_is_cancelled_not_escalated():
    r, p = one("fall_sim", 1, press_at_s=25.0)
    assert p["pre_alerts"] == 1 and p["cancelled"] == 1 and p["escalations"] == 0


def test_dropped_cane_picked_up_within_3s_is_not_an_alert():
    for seed in range(10):
        r, p = one("drop_hand", seed)
        assert p["episodes"] == 1 and p["pre_alerts"] == 0, seed
    for lying in (1.0, 2.0, 2.9):
        _, p = one("drop_hand", 7, lying_s=lying)
        assert p["pre_alerts"] == 0


def test_knocked_over_cane_picked_up_in_seconds_is_not_an_alert():
    for seed in range(8):
        _, p = one("knock_over", seed)
        assert p["episodes"] == 1 and p["pre_alerts"] == 0


def test_dropped_cane_left_on_floor_is_indistinguishable_from_fall():
    """Documented limitation: a cane left lying >13 s alerts, so it counts as a drop-vs-fall confusion."""
    r, p = one("drop_hand", 0, lying_s=40.0)
    assert p["pre_alerts"] == 1
    assert r["confusion_drop_vs_fall"]["drop (drop_hand+knock_over)"]["alert"] == 1


def test_mounted_rotated_sensor_uses_meta_upright():
    s = build_session([("walk", dict(secs=30.0)), ("fall_sim", dict(press_at_s=None))], seed=2, mount_deg=25)
    r = E.evaluate([s], with_features=False)
    assert r["per_label"]["walk"]["episodes"] == 0 and r["fall_sim"]["sensitivity"] == 1.0
    # without the calibrated upright the rotated mount reads ~25 deg of constant tilt
    assert np.degrees(np.arccos(s.upright()[2])) == pytest.approx(25, abs=0.5)
    del s.meta["upright"]
    est = s.upright()   # falls back to the first idle/walk segment's mean direction
    assert np.degrees(np.arccos(est @ np.array(build_session([("walk", {})], mount_deg=25).meta["upright"]))) < 20


def test_full_dataset_numbers_and_confusion():
    ds = make_dataset(seed=0, scale=0.5)
    r = E.evaluate(ds)
    assert r["fall_sim"]["sensitivity"] == 1.0
    assert r["false_alarms"]["pre_alerts"] == 0 and r["false_alarms"]["escalations"] == 0
    c = r["confusion_drop_vs_fall"]
    assert c["drop (drop_hand+knock_over)"]["alert"] == 0 and c["fall (fall_sim)"]["no_alert"] == 0
    f = r["per_label"]["walk"]["features_per_minute"]
    assert 45 <= f["strikes_per_min"] <= 65 and f["upright_s_per_min"] > 55
    assert r["per_label"]["car"]["features_per_minute"]["flat_s_per_min"] > 1
    assert r["per_label"]["idle"]["features_per_minute"]["strikes_per_min"] == 0
    json.dumps(r, default=float)  # machine-readable


def test_sweep_shows_tradeoffs(monkeypatch):
    monkeypatch.setattr(E, "SWEEP_OAT", {"still_required_s": [3, 10], "pre_alert_s": [30]})
    ds = make_dataset(seed=0, scale=0.4)
    rows = E.sweep(ds, "oat")
    by = {tuple(r["varied"]): r for r in rows}
    assert by[("(defaults)",)]["pre_alerts_per_hour"] == 0
    assert by[("still_required_s",)]["pre_alerts_per_hour"] > 0        # 3 s stillness false-alarms on drops
    txt = E.format_sweep(rows)
    assert "defaults" in txt and "FApre/h" in txt
    assert E.rank(rows, 1)[0]["pre_alerts_per_hour"] == 0


def test_cli_json_stdout_and_files(tmp_path, capsys):
    paths = []
    for i, s in enumerate(make_dataset(seed=0, scale=0.3)):
        p = str(tmp_path / f"s{i}.npz")
        save(s, p)
        paths.append(p)
    assert E.main(paths + ["--sweep", "none", "--json", "-"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["fall_sim"]["sensitivity"] == 1.0 and out["sweep"]["rows"] == []
    assert E.main(paths + ["--sweep", "none"]) == 0
    assert "SENSITIVITY" in capsys.readouterr().out


def test_unlabelled_gap_is_reported_not_crash():
    s = build_session([("fall_sim", dict(press_at_s=None))], seed=0)
    s.labels = []
    eps, _ = E.replay(s)
    assert eps and eps[0].label == "unlabelled"
