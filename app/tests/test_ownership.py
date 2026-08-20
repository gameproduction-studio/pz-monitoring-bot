from pzbot.ownership import classify_container, position_in_zone


def test_radius_is_measured_in_tiles_and_all_z_levels_by_default():
    zone = {"shape": "circle", "x": 100, "y": 100, "radius": 25}
    assert position_in_zone({"x": 125, "y": 100, "z": -1}, zone)
    assert not position_in_zone({"x": 126, "y": 100, "z": 0}, zone)


def test_owned_only_when_opened_or_inside_base():
    base = {"name": "Home", "shape": "circle", "x": 10, "y": 10, "radius": 5}
    untouched = {
        "containerId": "c1",
        "position": {"x": 50, "y": 50, "z": 0},
        "explored": False,
        "hasBeenLooted": False,
    }
    assert not classify_container(untouched, zones=[base], save_id="s")["owned"]

    opened = dict(untouched, explored=True)
    result = classify_container(opened, zones=[base], save_id="s")
    assert result["owned"]
    assert result["confidence"] == "medium"

    in_base = dict(untouched, position={"x": 12, "y": 10, "z": -1})
    result = classify_container(in_base, zones=[base], save_id="s")
    assert result["owned"]
    assert result["confidence"] == "exact"

