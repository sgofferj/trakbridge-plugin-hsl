from plugin.hsl import (
    HslPlugin,
    MODE_MAP,
    parse_hfp_topic,
)


def make_plugin(route_filter: str = "") -> HslPlugin:
    return HslPlugin({"hsl_route_filter": route_filter})


def test_parse_hfp_topic():
    topic = "/hfp/v2/journey/ongoing/vp/tram/00125/00125_2/1015/1/Tesla/16:19:12"
    assert parse_hfp_topic(topic) == ("tram", "1015")
    assert parse_hfp_topic("/short/topic") is None


def test_matches_filter_empty_shows_all():
    plugin = make_plugin("")
    assert plugin._matches_filter("HSL:1015", "15", "") is True
    assert plugin._matches_filter("HSL:9999", "", "") is True


def test_matches_filter_exact():
    plugin = make_plugin("15,M1,M2")
    assert plugin._matches_filter("HSL:1015", "15", "15,M1,M2") is True
    assert plugin._matches_filter("HSL:1001M1", "M1", "15,M1,M2") is True
    assert plugin._matches_filter("HSL:2550", "550", "15,M1,M2") is False


def test_matches_filter_wildcard_and_hsl_prefix():
    plugin = make_plugin("L*")
    assert plugin._matches_filter("HSL:1015L", "L1", "L*") is True
    assert plugin._matches_filter("HSL:1015", "15", "L*") is False


def test_mode_map():
    assert MODE_MAP["tram"] == "a-f-G-E-V-C-M"
    assert MODE_MAP["metro"] == "a-f-G-E-V-C-M"
    assert MODE_MAP["train"] == "a-f-G-E-V-C-M"
    assert MODE_MAP["ferry"] == "a-f-S-X-C"
    assert MODE_MAP["bus"] == "a-f-G-E-V-C-M-H"


def test_process_message_buffers_vehicle():
    import json

    plugin = make_plugin("M1")
    topic = "/hfp/v2/journey/ongoing/vp/metro/00125/00125_2/31M1/1/Test/16:19:12"
    vp = {
        "desi": "M1",
        "lat": 60.1710,
        "long": 24.9410,
        "oday": "2026-08-21",
        "start": "16:19",
        "dir": 1,
        "oper": 125,
        "veh": 2,
        "spd": 5.5,
        "hdg": 90,
        "occu": 2,
    }
    payload = json.dumps({"VP": vp}).encode()
    plugin._process_message(topic, payload)

    assert len(plugin._buffer) == 1
    entry = list(plugin._buffer.values())[0]
    assert entry["uid"].startswith("HSL-metro-31M1-")
    assert entry["name"] == "HSL M1"
    assert entry["cot_type"] == "a-f-G-E-V-C-M"
    assert entry["lat"] == 60.1710
    assert entry["lon"] == 24.9410
    assert entry["speed"] == 5.5
    assert entry["course"] == 90.0
    assert "#HSL" in entry["description"]
    assert "Cars: 125_2" in entry["description"]


def test_process_message_filtered_out():
    import json

    plugin = make_plugin("15")
    topic = "/hfp/v2/journey/ongoing/vp/bus/00001/00001_1/2001/1/Test/10:00:00"
    vp = {"desi": "550", "lat": 60.2, "long": 24.8, "oper": 1, "veh": 1}
    payload = json.dumps({"VP": vp}).encode()
    plugin._process_message(topic, payload)
    assert len(plugin._buffer) == 0
