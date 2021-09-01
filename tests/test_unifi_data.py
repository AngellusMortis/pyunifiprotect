"""Tests for pyunifiprotect.unifi_data"""

import base64
import json
from unittest.mock import patch

from pyunifiprotect.test_util.data import (
    legacy_process_camera,
    legacy_process_event,
    legacy_process_light,
    legacy_process_viewport,
)
from pyunifiprotect.unifi_data import (
    LIVE_RING_FROM_WEBSOCKET,
    EventType,
    ProtectWSPayloadFormat,
    decode_ws_frame,
    process_camera,
    process_event,
    process_light,
    process_viewport,
)
from tests.conftest import MockDatetime
from tests.sample_data.constants import CONSTANTS

PACKET_B64 = b"AQEBAAAAAHR4nB2MQQrCMBBFr1JmbSDNpJnRG4hrDzBNZqCgqUiriHh3SZb/Pd7/guRtWSucBtgfRTaFwwBV39c+zqUJskQW1DufUVwkJsfFxDGLyRFj0dSz+1r0dtFPa+rr2dDSD8YsyceUpskQxzjjHIIQMvz+hMoj/AIBAQAAAAA1eJyrViotKMnMTVWyUjA0MjawMLQ0MDDQUVDKSSwuCU5NzQOJmxkbACUszE0sLQ1rAVU/DPU="
PACKET_ACTION = {
    "action": "update",
    "newUpdateId": "7f67f2e0-0c3a-4787-8dfa-88afa934de6e",
    "modelKey": "nvr",
    "id": "1ca6046655f3314b3b22a738",
}
PACKET_DATA = {"uptime": 1230819000, "lastSeen": 1630081874991}


def test_decode_frame():
    packet_raw = base64.b64decode(PACKET_B64)

    raw_data, payload_format, position = decode_ws_frame(packet_raw, 0)

    assert json.loads(raw_data) == PACKET_ACTION
    assert payload_format == ProtectWSPayloadFormat.JSON
    assert position == 124

    raw_data, payload_format, position = decode_ws_frame(packet_raw, position)

    assert json.loads(raw_data) == PACKET_DATA
    assert payload_format == ProtectWSPayloadFormat.JSON
    assert position == 185


@patch("pyunifiprotect.unifi_protect_server.datetime", MockDatetime)
def test_process_viewport(viewport):
    data = process_viewport(CONSTANTS["server_id"], viewport, True)

    assert data == legacy_process_viewport(viewport, server_id=CONSTANTS["server_id"])


@patch("pyunifiprotect.unifi_protect_server.datetime", MockDatetime)
def test_process_light(light):
    data = process_light(CONSTANTS["server_id"], light, True)

    assert data == legacy_process_light(light, server_id=CONSTANTS["server_id"])


@patch("pyunifiprotect.unifi_protect_server.datetime", MockDatetime)
def test_process_camera(camera):
    host = "example.com"
    data = process_camera(CONSTANTS["server_id"], host, camera, True)

    assert data == legacy_process_camera(camera, host, server_id=CONSTANTS["server_id"])


def test_process_event_live(raw_events):
    applicable_events = []
    for event in raw_events:
        if event.get("type") in [EventType.MOTION.value, EventType.SMART_DETECT.value]:
            applicable_events.append(event)

    events = []
    for event in applicable_events:
        events.append(process_event(event, 0, LIVE_RING_FROM_WEBSOCKET))

    legacy_events = []
    for event in applicable_events:
        legacy_events.append(legacy_process_event(event, 0, LIVE_RING_FROM_WEBSOCKET))

    assert len(events) == len(legacy_events)

    # make it easier to debug if they are not
    for index in range(len(events)):
        assert events[index] == legacy_events[index]
