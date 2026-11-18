"""Pool / spa logic (pool.py) - the same behaviour as the hand-written
iAquaLink template sensors it replaces."""

from custom_components.room_tiles.pool import (
    BodyInput,
    PoolLogic,
    SystemInput,
    TimeToTarget,
    eta_text,
    short_text,
    status_text,
)


def shared(spa_mode="off", pump="on", pool=None, spa=None, now=1000.0, dropped_at=None):
    return SystemInput(
        layout="shared",
        bodies={"pool": pool or BodyInput(), "spa": spa or BodyInput()},
        spa_mode=spa_mode,
        pump=pump,
        now=now,
        dropped_at=dropped_at,
    )


def test_shared_pool_mode_heating():
    lg = PoolLogic("shared")
    r = lg.update(shared(pool=BodyInput(temp="79.4", heater_mode="heat", heater_action="heating", target=85)))
    assert (r["pool"].state, r["pool"].temp, r["pool"].target, r["pool"].active) == ("heating", 79, 85, True)
    assert r["spa"].state == "standby"
    assert status_text("pool", r["pool"], "~55 min") == "Heating to 85°, ~55 min left"
    assert status_text("spa", r["spa"], shared_mode="pool") == "Off - Pool running"
    assert short_text(r["pool"], "~55 min") == "Heating\n~55 min"


def test_shared_switching_to_spa_then_spa_reads():
    lg = PoolLogic("shared")
    lg.update(shared(pool=BodyInput(temp=80)))
    # spa mode on: the spa has no reading yet, the pump runs -> switching
    r = lg.update(shared(spa_mode="on", pool=BodyInput(temp=None), spa=BodyInput(temp=None), now=1010))
    assert r["spa"].state == "switching"
    assert status_text("spa", r["spa"]) == "Switching to Spa..."
    # the pool keeps its last reading, with its age, while on standby
    assert (r["pool"].state, r["pool"].temp, r["pool"].temp_age_s) == ("standby", 80, 10)
    r = lg.update(shared(spa_mode="on", spa=BodyInput(temp=82, heater_mode="heat", heater_action="idle", target=97), now=1060))
    assert (r["spa"].state, r["spa"].temp) == ("idle", 82)


def test_shared_spa_to_pool_old_body_still_reads_is_switching():
    lg = PoolLogic("shared")
    r = lg.update(shared(spa_mode="off", pump="off", pool=BodyInput(temp=None), spa=BodyInput(temp=96)))
    assert r["pool"].state == "switching"


def test_shared_pump_off():
    lg = PoolLogic("shared")
    r = lg.update(shared(pump="off", pool=BodyInput(temp=None), spa=BodyInput(temp=None)))
    assert r["pool"].state == "pump_off"


def test_short_dropout_keeps_values_then_offline():
    lg = PoolLogic("shared")
    lg.update(shared(pool=BodyInput(temp=80, heater_mode="heat", heater_action="heating", target=85)))
    r = lg.update(shared(spa_mode="unavailable", pump="unavailable", now=1050, dropped_at=1040))
    assert r["pool"].state == "heating"  # within 2 min: unchanged
    r = lg.update(shared(spa_mode="unavailable", pump="unavailable", now=1200, dropped_at=1040))
    assert r["pool"].state == "offline"
    assert status_text("pool", r["pool"]) == "Offline"


def test_separate_bodies_run_independently():
    lg = PoolLogic("separate")
    r = lg.update(
        SystemInput(
            layout="separate",
            bodies={
                "pool": BodyInput(temp=78, heater_mode="off", pump="on", target=84),
                "spa": BodyInput(temp=None, pump="off", target=100),
            },
            now=5,
        )
    )
    assert (r["pool"].state, r["pool"].active) == ("off", True)
    assert status_text("pool", r["pool"]) == "Heater off, set 84°"
    assert (r["spa"].state, r["spa"].active) == ("pump_off", False)


def test_one_body_only():
    lg = PoolLogic("spa")
    r = lg.update(SystemInput(layout="spa", bodies={"spa": BodyInput(temp=101, heater_mode="heat", heater_action="idle", target=102)}))
    assert list(r) == ["spa"]
    assert r["spa"].state == "idle"
    assert status_text("spa", r["spa"]) == "Heater on, set 102°"


def test_time_to_target_least_squares():
    tt = TimeToTarget()
    key = "spa:heating"
    # ~1 F per 3 min with jitter (the spa, 2026-11-05)
    readings = [(0, 83), (180, 81), (360, 83), (540, 84), (720, 85), (900, 86)]
    eta = None
    for t, temp in readings:
        eta = tt.update(t, key, True, temp, 97)
    assert eta is not None and 25 <= eta <= 45
    assert eta_text(eta).startswith("~")
    # not running: no estimate; a new run starts fresh
    assert tt.update(1000, key, False, 86, 97) is None
    assert tt.update(2000, "pool:heating", True, 80, 85) is None
    assert len(tt.samples) == 1


def _run(key, readings, target):
    """Feed (seconds, temp) readings, updating every 5 min in between like
    the live sensor (a 10 min gap would start a new run)."""
    tt, eta = TimeToTarget(), None
    for (t, temp), nxt in zip(readings, [*readings[1:], None]):
        end = nxt[0] if nxt else t + 1
        for now in range(t, end, 300):
            eta = tt.update(now, key, True, temp, target)
    return eta


def test_time_to_target_chilling():
    # falling 1 degree / 10 min toward 80: ~4 degrees to go
    eta = _run("pool:cooling", [(i * 600, 88 - i) for i in range(5)], 80)
    assert eta is not None and 30 <= eta <= 50


def test_time_to_target_slow_pool_over_a_day():
    # 1 degree / 2 h, 15 to go: ~30 h - still shown, in hours
    eta = _run("pool:heating", [(i * 7200, 70 + i) for i in range(5)], 89)
    assert eta is not None and 25 * 60 <= eta <= 35 * 60
    assert eta_text(eta).startswith("~3")


def test_time_to_target_slow_pool_with_jitter():
    # 1 degree every 2 h; each step flickers back and forth a few times
    readings, t = [], 0
    for temp in range(78, 83):
        for flick in (temp, temp - 1, temp, temp - 1, temp):
            readings.append((t, flick))
            t += 300
        t += 7200 - 5 * 300
    eta = _run("pool:heating", readings, 90)
    assert eta is not None and 14 * 60 <= eta <= 22 * 60  # ~8 degrees at 0.5 / h


def test_time_to_target_flat_wrong_way_reached():
    # flat (jitter only): no estimate, never a huge number
    assert _run("pool:heating", [(i * 600, t) for i, t in enumerate([80, 81, 80, 81, 80, 82, 80])], 95) is None
    # nearly flat: 2 degrees in 11 h, 30 to go = days -> no estimate
    assert _run("pool:heating", [(0, 70), (20000, 71), (40000, 72)], 102) is None
    # heating but falling / chilling but rising: no estimate
    assert _run("pool:heating", [(i * 600, 88 - i) for i in range(5)], 95) is None
    assert _run("pool:cooling", [(i * 600, 80 + i) for i in range(5)], 75) is None
    # already at or past the target: no "~1m"
    assert _run("pool:heating", [(i * 600, 90 + i) for i in range(5)], 93) is None
    assert _run("pool:cooling", [(i * 600, 90 - i) for i in range(5)], 87) is None


def test_eta_text():
    assert eta_text(None) == ""
    assert eta_text(55) == "~55m"
    assert eta_text(70) == "~1h 10m"



# ---- every equipment combination (user, 2026-11-09) ---------------------------


def one(layout, **body):
    return SystemInput(layout=layout, bodies={layout: BodyInput(**body)}, now=10)


def test_pool_with_heater_no_spa():
    lg = PoolLogic("pool")
    r = lg.update(one("pool", temp=80, heater_mode="heat", heater_action="heating", target=86, pump="on"))
    assert list(r) == ["pool"]
    assert (r["pool"].state, r["pool"].target) == ("heating", 86)
    assert status_text("pool", r["pool"], has_pump=True) == "Heating to 86°"
    # pump off: no reading, says so
    r = lg.update(one("pool", temp=None, heater_mode="heat", heater_action="idle", target=86, pump="off"))
    assert (r["pool"].state, r["pool"].temp, r["pool"].temp_age_s is not None) == ("pump_off", 80, True)
    # no pump set up and no reading: still follows the heater (last reading shown)
    lg2 = PoolLogic("pool")
    lg2.update(one("pool", temp=81, heater_mode="heat", heater_action="heating", target=86))
    r = lg2.update(one("pool", temp=None, heater_mode="heat", heater_action="heating", target=86))
    assert (r["pool"].state, r["pool"].temp) == ("heating", 81)


def test_pool_no_heater_no_spa():
    lg = PoolLogic("pool")
    r = lg.update(one("pool", temp=78, pump="on", has_heater=False))
    assert (r["pool"].state, r["pool"].heater, r["pool"].target) == ("on", "none", None)
    assert status_text("pool", r["pool"], has_pump=True) == "Pump on"
    assert short_text(r["pool"], has_pump=True) == "Pump on"
    assert lg.update(one("pool", temp=None, pump="off", has_heater=False))["pool"].state == "pump_off"
    # no pump either: just the temperature
    r = PoolLogic("pool").update(one("pool", temp=78, has_heater=False))
    assert (r["pool"].state, status_text("pool", r["pool"]), short_text(r["pool"])) == ("on", "", "")


def test_spa_with_heater_no_pool():
    lg = PoolLogic("spa")
    r = lg.update(one("spa", temp=100, heater_mode="heat", heater_action="heating", target=102))
    assert list(r) == ["spa"]
    assert (r["spa"].state, r["spa"].active) == ("heating", True)
    assert status_text("spa", r["spa"]) == "Heating to 102°"


def test_two_pumps_one_heater_spa_independent():
    """Separate pool and spa: own pumps, the heater on the spa only."""
    lg = PoolLogic("separate")
    inp = SystemInput(
        layout="separate",
        bodies={
            "pool": BodyInput(temp=77, pump="on", has_heater=False),
            "spa": BodyInput(temp=99, pump="on", heater_mode="heat", heater_action="heating", target=102),
        },
        now=10,
    )
    r = lg.update(inp)
    assert (r["pool"].state, r["pool"].heater) == ("on", "none")
    assert (r["spa"].state, r["spa"].target) == ("heating", 102)
    # the spa's pump off: only the spa stops
    inp.bodies["spa"] = BodyInput(temp=None, pump="off", heater_mode="heat", heater_action="idle", target=102)
    r = lg.update(inp)
    assert (r["pool"].state, r["spa"].state) == ("on", "pump_off")
    # one pump dropping out takes the system offline (like the shared one)
    inp.bodies["spa"] = BodyInput(temp=None, pump="unavailable", has_heater=True)
    assert lg.update(inp)["pool"].state == "offline"


def test_shared_without_heaters():
    lg = PoolLogic("shared")
    r = lg.update(shared(pool=BodyInput(temp=79, has_heater=False), spa=BodyInput(has_heater=False)))
    assert (r["pool"].state, r["spa"].state) == ("on", "standby")
    assert status_text("pool", r["pool"], has_pump=True) == "Pump on"


def test_heater_on_with_the_pump_off_waits_for_the_pump():
    """Heaters need flow; the controller starts the pump (Jandy does)."""
    lg = PoolLogic("shared")
    r = lg.update(shared(pump="off", pool=BodyInput(temp=None, heater_mode="heat", target=85), spa=BodyInput(temp=None)))
    assert r["pool"].state == "pump_off"
    assert status_text("pool", r["pool"]) == "Heater on - waiting for the pump"
    assert short_text(r["pool"]) == "Waiting for pump"
    # heater off: plainly off
    r = lg.update(shared(pump="off", pool=BodyInput(temp=None, heater_mode="off", target=85), spa=BodyInput(temp=None)))
    assert (status_text("pool", r["pool"]), short_text(r["pool"])) == ("Pump off", "Pump off")
