"""Robot vacuum profile logic (robot.py) - the Matic Alert / Matic Tile
template sensors' behaviour, for any vacuum."""

from custom_components.room_tiles.robot import alert_of, tile_text, view


def test_alerts():
    assert alert_of("no_error") == ("none", "")
    assert alert_of("water_tank_lid_open") == ("none", "")  # expected while refilling
    assert alert_of("water_tank_empty") == ("attention", "Refill water tank")
    assert alert_of("dust_bin_full") == ("attention", "Empty dust bin")
    assert alert_of("stuck") == ("error", "Stuck - needs help")
    assert alert_of("some_new_error") == ("error", "Some new error")
    assert alert_of(None) == ("none", "")


def test_tile_classes_and_status():
    assert view("cleaning").status == "Cleaning"
    assert view("cleaning", room="Kitchen").status == "Cleaning Kitchen"
    assert (view("docked").cls, view("docked").status) == ("docked", "Docked")
    assert view("returning").status == "Returning to dock"
    assert (view("unavailable").cls, view("unavailable").status) == ("offline", "Offline")
    # "needs you" wins over the state, shown as attention - not a fault
    v = view("docked", "water_tank_empty")
    assert (v.cls, v.status, v.alert) == ("attention", "Refill water tank", "attention")
    v = view("cleaning", "stuck")
    assert (v.cls, v.status) == ("error", "Error: Stuck - needs help")
    assert view("error").status == "Error"
    assert view("idle").cls == "idle"
    # another brand without Matter errors: just its state
    assert view("cleaning", None).cls == "cleaning"


def test_tile_text():
    assert tile_text(view("cleaning")) == "cleaning|Cleaning||"
    assert tile_text(view("cleaning", room="Kitchen"), "kitchen", ["hall", "office"]) == "cleaning|Cleaning Kitchen|kitchen|hall,office"


def test_room_queue_like_the_matic_queue():
    from custom_components.room_tiles.robot import QUEUE_GIVE_UP_S, RoomQueue, QueueStep

    q = RoomQueue(queue=[])
    q.add("kitchen")
    q.add("hall")
    q.add("kitchen")  # already queued: to the end
    assert q.queue == ["hall", "kitchen"]
    # Start: the first room; it leaves the queue once clean_area went out
    assert q.start("docked", "none") == QueueStep("clean", "hall")
    q.sent("hall")
    assert (q.current, q.queue) == ("hall", ["kitchen"])
    q.add("hall")  # being cleaned: not queued again
    assert q.queue == ["kitchen"]
    # an add that starts the queue (manual off) never redirects a room in progress
    assert q.start("idle", "none", manual=False) is None
    # done cleanly: returning with no alert -> the next room at once
    assert q.on_state("cleaning", "returning", "none") == QueueStep("clean", "kitchen")
    # returning WITH an alert is not done
    assert q.on_state("cleaning", "returning", "error") is None
    q.sent("kitchen")
    # the last room done: the queue is finished
    assert q.on_state("cleaning", "returning", "none") is None
    assert (q.current, q.queue) == (None, [])


def test_room_queue_pause_errors_and_order():
    from custom_components.room_tiles.robot import QUEUE_GIVE_UP_S, RoomQueue, QueueStep

    q = RoomQueue(queue=["a", "b", "c"], current="x")
    assert q.start("paused", "none") == QueueStep("resume")  # paused: resume, nothing else
    assert q.start("docked", "attention") == QueueStep("clean", "x")  # an alert: that room again
    q.move("c", 0)
    assert q.queue == ["c", "a", "b"]
    q.remove("a")
    assert q.queue == ["c", "b"]
    # an alert with a room in progress: 12 h unresolved -> cancel and clear
    assert q.on_alert("error", 1000) is False
    assert q.on_alert("error", 1000 + QUEUE_GIVE_UP_S - 1) is False
    assert q.on_alert("error", 1000 + QUEUE_GIVE_UP_S) is True
    assert (q.current, q.queue) == (None, [])
    q2 = RoomQueue(queue=["a"], current="x")
    assert q2.stop_and_clear() == QueueStep("dock") and (q2.current, q2.queue) == (None, [])


def test_room_queue_lets_go_when_taken_over():
    """Matic (idle_stops): a finished room goes straight to returning; a stop
    or a "go home" from its app turns it idle first -> the queue is cleared,
    the status says so until it docks. Its own room switch's idle blip
    (`ours`) isn't a takeover."""
    from custom_components.room_tiles.robot import RoomQueue, QueueStep, idle_is_a_stop, view

    assert idle_is_a_stop("Matic Robots, Inc") and not idle_is_a_stop("Ecovacs") and not idle_is_a_stop(None)
    q = RoomQueue(queue=["hall"], current="kitchen")
    assert q.on_state("cleaning", "idle", "none", ours=True, idle_stops=True) is None  # our own switch
    assert (q.current, q.queue, q.taken_over) == ("kitchen", ["hall"], False)
    assert q.on_state("cleaning", "idle", "none", idle_stops=True) is None  # stopped from its app
    assert (q.current, q.queue, q.taken_over) == (None, [], True)
    assert view("returning", "no_error", taken_over=True).status == "Queue cleared - used elsewhere"
    assert view("error", "stuck", taken_over=True).cls == "error"  # (an error still shows)
    assert q.on_state("idle", "returning", "none", idle_stops=True) is None  # its trip home: nothing to send
    assert q.on_state("returning", "docked", "none", idle_stops=True) is None and not q.taken_over
    # a room it finished: still the next one
    q = RoomQueue(queue=["hall"], current="kitchen")
    assert q.on_state("cleaning", "returning", "none", idle_stops=True) == QueueStep("clean", "hall")
    # paused and resumed from its app: the queue waits, nothing else
    q = RoomQueue(queue=["hall"], current="kitchen")
    assert q.on_state("cleaning", "paused", "none", idle_stops=True) is None
    assert q.on_state("paused", "cleaning", "none", idle_stops=True) is None and q.current == "kitchen"
    # other makers (untested): idle still counts as a finished room
    q = RoomQueue(queue=["hall"], current="kitchen")
    assert q.on_state("cleaning", "idle", "none") == QueueStep("clean", "hall") and not q.taken_over
    # a job the queue never started moves nothing
    q = RoomQueue(queue=["hall"])
    assert q.on_state("cleaning", "returning", "none", idle_stops=True) is None and q.queue == ["hall"]


def test_clean_mode_option():
    from custom_components.room_tiles.robot import mode_option

    matic = ["Quick Vacuum", "Vacuum", "Deep Vacuum", "Quick Mop", "Mop", "Deep Mop", "Quick Vacuum+Mop", "Vacuum+Mop", "Deep Vacuum+Mop"]
    assert mode_option(matic, "both") == "Vacuum+Mop"
    assert mode_option(matic, "vacuum") == "Vacuum"
    assert mode_option(matic, "mop") == "Mop"
    assert mode_option(["Auto", "Quiet"], "both") is None  # no such mode: left as it is

