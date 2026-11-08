import numpy as np
import pytest

from tools import session as S
from tools.synth_sessions import build_session


def small():
    return build_session([("idle", dict(secs=5.0)), ("walk", dict(secs=10.0))], seed=1)


@pytest.mark.parametrize("ext", ["npz", "csv"])
def test_roundtrip(tmp_path, ext):
    s = small()
    p = str(tmp_path / f"s.{ext}")
    S.save(s, p)
    t = S.load(p)
    assert t.sample_rate_hz == s.sample_rate_hz and t.n == s.n
    assert np.allclose(t.acc, s.acc, atol=1e-4)
    assert t.labels == s.labels and t.meta["source"] == "synthetic"
    assert np.array_equal(t.button, s.button)


def test_validation_errors():
    s = small()
    s.labels.append(dict(t_start=0.0, t_end=3.0, label="walk"))
    with pytest.raises(S.SessionError, match="overlapping"):
        s.validate()
    s2 = small()
    s2.labels[0]["label"] = "dance"
    with pytest.raises(S.SessionError, match="unknown label"):
        s2.validate()
    s3 = small()
    s3.labels[0]["t_end"] = 9999
    with pytest.raises(S.SessionError, match="bad label interval"):
        s3.validate()


def test_upright_prefers_meta_then_idle_segment():
    s = small()
    del s.meta["upright"]
    assert np.allclose(s.upright(), [0, 0, 1], atol=0.05)
    s.meta["upright"] = [0, 1, 0]
    assert np.allclose(s.upright(), [0, 1, 0])


def test_resample_100_to_50():
    t = np.arange(1000) / 100.0
    acc = np.stack([np.zeros(1000), np.zeros(1000), 1 + 0.1 * np.sin(t)], 1)
    r = S.Session(100, acc, np.zeros(1000, bool), [dict(t_start=0, t_end=9, label="idle")]).resampled(50)
    assert r.sample_rate_hz == 50 and abs(r.n - 500) <= 1 and "upright" in r.meta


def _fw_csv(path, secs, rate=100.0, t0=1_762_600_000.0, acc=(0, 0, 1.0), jitter=True):
    rng = np.random.default_rng(0)
    n = int(secs * rate)
    with open(path, "w") as f:
        f.write("t,ax,ay,az\n")
        for i in range(n):
            t = t0 + i / rate + (rng.uniform(-0.001, 0.001) if jitter else 0)
            f.write(f"{t:.3f},{acc[0]:.4f},{acc[1]:.4f},{acc[2]:.4f}\n")


def test_import_firmware_record_csv(tmp_path):
    a, b = tmp_path / "walking_101500.csv", tmp_path / "dropped_101700.csv"
    _fw_csv(a, 20)
    _fw_csv(b, 6, acc=(1.0, 0, 0))
    s = S.import_firmware([str(a), str(b)], person="p1")
    assert s.sample_rate_hz == 50 and abs(s.n - 26 * 50) <= 2
    assert [l["label"] for l in s.labels] == ["walk", "drop_hand"]
    assert abs(s.labels[0]["t_end"] - 20) < 0.1 and abs(s.labels[1]["t_start"] - s.labels[0]["t_end"]) < 1e-9
    assert s.meta["source_rates_hz"][0] == pytest.approx(100, abs=2) and not s.button.any()
    assert np.allclose(s.acc[-10:], [1, 0, 0], atol=1e-3)
    out = str(tmp_path / "o.npz")
    S.save(s, out)
    assert S.load(out).n == s.n


def test_import_unknown_firmware_label_becomes_other_and_gaps_reported(tmp_path):
    p = tmp_path / "stairs_090000.csv"
    _fw_csv(p, 10, jitter=False)
    lines = p.read_text().splitlines()
    p.write_text("\n".join(lines[:300] + lines[400:]) + "\n")   # drop 1 s of samples
    s = S.import_firmware([str(p)])
    assert s.labels[0]["label"] == "other" and s.meta["gaps_s"] == [1.01]


def test_cli_info_and_import(tmp_path, capsys):
    p = tmp_path / "still_000001.csv"
    _fw_csv(p, 5)
    o = str(tmp_path / "x.npz")
    S.main(["import-firmware", str(p), "--out", o])
    S.main(["info", o])
    assert "idle" in capsys.readouterr().out
