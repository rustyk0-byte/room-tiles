"""Areas hidden on the user's dashboards start hidden in Room Tiles."""

from custom_components.room_tiles.dashboards import hidden_in


def test_both_dashboard_forms():
    areas_dashboard = {"strategy": {"type": "areas", "areas_display": {"hidden": ["fan_switches"], "order": ["kitchen"]}}}
    overview = {"strategy": {"type": "original-states", "areas": {"hidden": ["cameras", "fan_switches"]}}}
    assert hidden_in(areas_dashboard) == {"fan_switches"}
    assert hidden_in(overview) == {"cameras", "fan_switches"}


def test_other_dashboards_hide_nothing():
    assert hidden_in({"views": [{"cards": []}]}) == set()
    assert hidden_in(None) == set()
    assert hidden_in({"strategy": {"areas": {"hidden": "x"}}}) == set()
