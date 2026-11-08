import numpy as np
from cane.canesense.fsm import FallFSM, State

UP = np.array([0.0, 0.0, 1.0])
HZ = 50


def run(fsm, seconds, acc, button=False, t0=0.0, rng=None):
    rng = rng or np.random.default_rng(0)
    events, t = [], t0
    for _ in range(int(seconds * HZ)):
        a = np.array(acc, float) + rng.normal(0, 0.005, 3)
        ev = fsm.update(t, a, button)
        if ev:
            events.append(ev)
        t += 1 / HZ
    return events, t


def drop_and_lie(fsm):
    ev, t = run(fsm, 2, UP)                      # held upright
    ev2, t = run(fsm, 0.1, [4.0, 0, 0.5], t0=t)  # impact
    return ev + ev2, t


def test_walking_never_triggers():
    f = FallFSM(UP)
    rng = np.random.default_rng(1)
    t = 0.0
    for i in range(60 * HZ):
        a = UP + np.array([0.1 * np.sin(i / 5), 0, 0.3 * np.sin(i / 3)])
        assert f.update(t, a + rng.normal(0, 0.01, 3), False) is None
        t += 1 / HZ
    assert f.state is State.MONITORING and f.buzzer == "off"


def test_drop_then_button_cancels():
    f = FallFSM(UP)
    _, t = drop_and_lie(f)
    _, t = run(f, 15, [1.0, 0, 0.0], t0=t)       # lying flat, still
    assert f.state is State.PRE_ALERT and f.buzzer == "beep"
    run(f, 0.5, [1.0, 0, 0.0], button=True, t0=t)
    ev, t = run(f, 0.5, [1.0, 0, 0.0], button=False, t0=t + 0.5)
    assert [e.outcome for e in ev] == ["cancelled_by_user"]
    assert f.state is State.MONITORING and f.buzzer == "off"


def test_no_cancel_escalates_and_event_is_recorded():
    f = FallFSM(UP)
    _, t = drop_and_lie(f)
    ev, t = run(f, 50, [1.0, 0, 0.0], t0=t)
    assert [e.outcome for e in ev] == ["escalated"]
    assert f.state is State.ALERT and f.buzzer == "continuous"
    run(f, 3.5, [1.0, 0, 0.0], button=True, t0=t)  # long press acks locally
    assert f.state is State.MONITORING and f.buzzer == "off" and f.acknowledged_on_cane


def test_picked_up_quickly_is_not_an_alert():
    f = FallFSM(UP)
    _, t = drop_and_lie(f)
    _, t = run(f, 1.5, [1.0, 0, 0.0], t0=t)
    run(f, 5, UP, t0=t)
    assert f.state is State.MONITORING and f.buzzer == "off"


def test_long_press_in_monitoring_is_help_request():
    f = FallFSM(UP)
    ev, _ = run(f, 4, UP, button=True)
    assert [e.kind for e in ev] == ["help_request"]
