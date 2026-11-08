import io

import pytest

from tools import record_session as R
from tools.session import load


def test_parse_plan():
    assert R.parse_plan("walk:120, idle:60") == [("walk", 120.0), ("idle", 60.0)]
    with pytest.raises(ValueError):
        R.parse_plan("dance:5")
    with pytest.raises(ValueError):
        R.parse_plan("")


def test_stream_source_skips_header_and_bad_lines_and_reads_button():
    text = "ax,ay,az,button\n0,0,1\n0.1,0,1.0,1\n12,partial\n0,0,1,0\n"
    src = R.StreamSource(io.StringIO(text))
    got = []
    while (r := src.read()) is not None:
        got.append(r)
    assert len(got) == 3 and got[1][1] is True and src.bad == 2


def test_record_from_stream_labels_and_rate():
    lines = [f"0,0,1,{int(i == 150)}" for i in range(500)]
    s = R.record(R.StreamSource(iter(lines)), [("idle", 4), ("walk", 6)], 50, person="p", notes="n")
    assert s.n == 500 and s.sample_rate_hz == 50
    assert [(l["label"], l["t_start"], l["t_end"]) for l in s.labels] == [("idle", 0, 4), ("walk", 4, 10)]
    assert s.button[150] and s.meta["person"] == "p"


def test_truncated_stream_keeps_partial_segment_and_empty_raises():
    s = R.record(R.StreamSource(iter(["0,0,1"] * 120)), [("idle", 1), ("walk", 5), ("sit", 5)], 50)
    assert [l["label"] for l in s.labels] == ["idle", "walk"] and s.n == 120
    with pytest.raises(RuntimeError):
        R.record(R.StreamSource(iter([])), [("idle", 1)], 50)


def test_on_segment_callback_order():
    seen = []
    R.record(R.StreamSource(iter(["0,0,1"] * 100)), [("idle", 1), ("walk", 1)], 50,
             on_segment=lambda l, s: seen.append(l))
    assert seen == ["idle", "walk"]


def test_record_sim_all_labels_valid():
    s = R.record_sim([(l, 10) for l in ["walk", "idle", "sit", "lean", "drop_hand", "knock_over",
                                        "floor_tap", "fall_sim", "car", "other"]], seed=3)
    assert {l["label"] for l in s.labels} == set(R.LABELS)
    assert s.sample_rate_hz == 50 and s.meta["upright"]


def test_i2c_is_documented_stub():
    with pytest.raises(NotImplementedError):
        R.I2CSource()


def test_cli_sim_writes_loadable_file(tmp_path):
    out = str(tmp_path / "r.npz")
    R.main(["--source", "sim", "--plan", "walk:20,drop_hand:0", "--out", out])
    s = load(out)
    assert [l["label"] for l in s.labels] == ["walk", "drop_hand"]
    assert abs(s.labels[0]["t_end"] - 20) < 0.1


def test_cli_stream_file(tmp_path):
    f = tmp_path / "in.csv"
    f.write_text("\n".join(["0,0,1"] * 300))
    out = str(tmp_path / "r.csv")
    R.main(["--source", "stream", "--input", str(f), "--plan", "idle:6", "--out", out])
    assert load(out).n == 300
