"""Tests for pyunifiprotect.unifi_protect_server."""
# pylint: disable=protected-access


import asyncio
import base64
from copy import deepcopy
from datetime import timedelta
from typing import Any, Callable, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from pyunifiprotect import ProtectApiClient
from pyunifiprotect.data import EventType, WSPacket
from pyunifiprotect.data.base import ProtectModel
from pyunifiprotect.data.devices import Camera
from pyunifiprotect.data.websocket import (
    WSAction,
    WSJSONPacketFrame,
    WSSubscriptionMessage,
)
from pyunifiprotect.utils import to_js_time
from tests.conftest import MockDatetime, MockWebsocket

PACKET_RAW = "AQEBAAAAAHR4nCXMQQrCMBBA0auUWRvIpJOm8Qbi2gNMZiZQ0NRFqIh4dwluP7z/AZa+7Q3OE7AqnCZo9ro9lbtddFRPhCayuOorOyqYXfEJXcprEqQZ55UHe+xq96u9h7HDWh9x+y+UqeZAsUrQrCFajFQWgu8PBLYjMAIBAQAAAAC2eJxVjr0KwzAMhF8leO6QOLZDOrdT126lg2PLxRA7wVYKIeTdK1PoD2jQfTodtzFcZ2DHiiUfH+xQsYw6IYFGtbyplaKRnDhE+0u7N81mSuW9LnugzxMgGLxSaCZ8u//z8xMifg4BUFuNmvS2kzY6QCqKdaaXsrNOcSN1ywfbgXGtg1JwpjSPfopkjMs4EloypK/ypSirrRau50I6w21vuQQpxaBEiQiThfECa/FBqcT2F6ZyTac="


@pytest.fixture
def packet():
    return WSPacket(base64.b64decode(PACKET_RAW))


class SubscriptionTest:
    callback_count: int = 0
    unsub: Optional[Callable[[], None]] = None

    def callback(self, msg: WSSubscriptionMessage):
        self.callback_count += 1

        assert isinstance(msg.new_obj, ProtectModel)

        if msg.action == WSAction.ADD:
            assert msg.old_obj is None
        else:
            assert isinstance(msg.old_obj, ProtectModel)
            assert msg.old_obj.update_from_dict(msg.changed_data) == msg.new_obj

        if self.callback_count == 2:
            raise Exception()

        if self.callback_count >= 3 and self.unsub is not None:
            self.unsub()


@pytest.mark.asyncio
async def test_ws_all(protect_client_ws: ProtectApiClient, ws_messages: Dict[str, Dict[str, Any]]):
    protect_client = protect_client_ws
    sub = SubscriptionTest()
    sub.unsub = protect_client.subscribe_websocket(sub.callback)

    # wait for ws connection
    for _ in range(60):
        if protect_client.is_ws_connected:
            break
        await asyncio.sleep(0.5)

    ws_connect: Optional[MockWebsocket] = protect_client._ws_connection  # type: ignore
    assert ws_connect is not None

    while protect_client.is_ws_connected:
        await asyncio.sleep(0.1)

    assert ws_connect.count == len(ws_messages)
    assert ws_connect.now == float(list(ws_messages.keys())[-1])
    assert sub.callback_count == 3


@pytest.mark.asyncio
@patch("pyunifiprotect.api.datetime", MockDatetime)
async def test_ws_event_ring(protect_client_no_debug: ProtectApiClient, now, camera, packet: WSPacket):
    protect_client = protect_client_no_debug

    def get_camera():
        return protect_client.bootstrap.cameras[camera["id"]]

    bootstrap_before = protect_client.bootstrap.unifi_dict()
    camera_before = get_camera().copy()

    expected_updated_id = "0441ecc6-f0fa-4b19-b071-7987c143138a"
    expected_event_id = "bf9a241afe74821ceffffd05"

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore
    action_frame.data["newUpdateId"] = expected_updated_id

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore
    data_frame.data = {
        "id": expected_event_id,
        "type": "ring",
        "start": to_js_time(now - timedelta(seconds=1)),
        "end": to_js_time(now),
        "score": 0,
        "smartDetectTypes": [],
        "smartDetectEvents": [],
        "camera": camera["id"],
        "partition": None,
        "user": None,
        "metadata": {},
        "thumbnail": f"e-{expected_event_id}",
        "heatmap": f"e-{expected_event_id}",
        "modelKey": "event",
    }

    msg = MagicMock()
    msg.data = packet.pack_frames()

    protect_client._process_ws_message(msg)

    camera_index = -1
    for index, camera_dict in enumerate(bootstrap_before["cameras"]):
        if camera_dict["id"] == camera["id"]:
            camera_index = index
            break

    camera_before.last_ring = now - timedelta(seconds=1)
    bootstrap_before["cameras"][camera_index]["lastRing"] = to_js_time(camera_before.last_ring)
    bootstrap_before["lastUpdateId"] = expected_updated_id
    bootstrap = protect_client.bootstrap.unifi_dict()
    camera = get_camera()

    event = camera.last_ring_event
    camera_before.last_ring_event_id = None
    camera.last_ring_event_id = None

    assert bootstrap == bootstrap_before
    assert camera.dict() == camera_before.dict()
    assert event.id == expected_event_id
    assert event.type == EventType.RING
    assert event.thumbnail_id == f"e-{expected_event_id}"
    assert event.heatmap_id == f"e-{expected_event_id}"
    assert event.start == camera.last_ring


@pytest.mark.asyncio
@patch("pyunifiprotect.api.datetime", MockDatetime)
async def test_ws_event_motion_in_progress(protect_client_no_debug: ProtectApiClient, now, camera, packet: WSPacket):
    protect_client = protect_client_no_debug

    def get_camera():
        return protect_client.bootstrap.cameras[camera["id"]]

    bootstrap_before = protect_client.bootstrap.unifi_dict()
    camera_before = get_camera().copy()

    expected_updated_id = "0441ecc6-f0fa-4b19-b071-7987c143138a"
    expected_event_id = "bf9a241afe74821ceffffd05"

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore
    action_frame.data["newUpdateId"] = expected_updated_id
    action_frame.data["id"] = expected_event_id

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore
    data_frame.data = {
        "id": expected_event_id,
        "type": "motion",
        "start": to_js_time(now - timedelta(seconds=30)),
        "end": None,
        "score": 0,
        "smartDetectTypes": [],
        "smartDetectEvents": [],
        "camera": camera["id"],
        "partition": None,
        "user": None,
        "metadata": {},
        "thumbnail": f"e-{expected_event_id}",
        "heatmap": f"e-{expected_event_id}",
        "modelKey": "event",
    }

    msg = MagicMock()
    msg.data = packet.pack_frames()

    protect_client._process_ws_message(msg)

    camera_index = -1
    for index, camera_dict in enumerate(bootstrap_before["cameras"]):
        if camera_dict["id"] == camera["id"]:
            camera_index = index
            break

    camera_before.is_motion_detected = True
    bootstrap_before["cameras"][camera_index]["isMotionDetected"] = True
    bootstrap_before["lastUpdateId"] = expected_updated_id
    bootstrap = protect_client.bootstrap.unifi_dict()
    camera_obj = get_camera()

    assert bootstrap == bootstrap_before
    assert camera_obj == camera_before

    bootstrap_before = protect_client.bootstrap.unifi_dict()
    camera_before = get_camera().copy()

    expected_updated_id = "7d06fdd0-76be-4e65-9b61-9406d4ac1433"

    action_frame.data["newUpdateId"] = expected_updated_id
    action_frame.data["action"] = "update"

    data_frame.data = {"end": to_js_time(now)}

    msg = MagicMock()
    msg.data = packet.pack_frames()

    protect_client._process_ws_message(msg)

    camera_index = -1
    for index, camera_dict in enumerate(bootstrap_before["cameras"]):
        if camera_dict["id"] == camera["id"]:
            camera_index = index
            break

    camera_before.last_motion = now
    camera_before.is_motion_detected = False
    bootstrap_before["cameras"][camera_index]["lastMotion"] = to_js_time(camera_before.last_motion)
    bootstrap_before["cameras"][camera_index]["isMotionDetected"] = False
    bootstrap_before["lastUpdateId"] = expected_updated_id
    bootstrap = protect_client.bootstrap.unifi_dict()
    camera_obj = get_camera()

    event = camera_obj.last_motion_event
    camera_obj.last_motion_event_id = None
    camera_before.last_motion_event_id = None

    assert bootstrap == bootstrap_before
    assert camera_obj.dict() == camera_before.dict()
    assert event.id == expected_event_id
    assert event.type == EventType.MOTION
    assert event.thumbnail_id == f"e-{expected_event_id}"
    assert event.heatmap_id == f"e-{expected_event_id}"
    assert event.start == (now - timedelta(seconds=30))
    assert event.end == camera_obj.last_motion


@pytest.mark.asyncio
@patch("pyunifiprotect.api.datetime", MockDatetime)
async def test_ws_event_motion(protect_client_no_debug: ProtectApiClient, now, camera, packet: WSPacket):
    protect_client = protect_client_no_debug

    def get_camera():
        return protect_client.bootstrap.cameras[camera["id"]]

    bootstrap_before = protect_client.bootstrap.unifi_dict()
    camera_before = get_camera().copy()

    expected_updated_id = "0441ecc6-f0fa-4b19-b071-7987c143138a"
    expected_event_id = "bf9a241afe74821ceffffd05"

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore
    action_frame.data["newUpdateId"] = expected_updated_id

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore
    data_frame.data = {
        "id": expected_event_id,
        "type": "motion",
        "start": to_js_time(now - timedelta(seconds=30)),
        "end": to_js_time(now),
        "score": 0,
        "smartDetectTypes": [],
        "smartDetectEvents": [],
        "camera": camera["id"],
        "partition": None,
        "user": None,
        "metadata": {},
        "thumbnail": f"e-{expected_event_id}",
        "heatmap": f"e-{expected_event_id}",
        "modelKey": "event",
    }

    msg = MagicMock()
    msg.data = packet.pack_frames()

    protect_client._process_ws_message(msg)

    camera_index = -1
    for index, camera_dict in enumerate(bootstrap_before["cameras"]):
        if camera_dict["id"] == camera["id"]:
            camera_index = index
            break

    camera_before.last_motion = now
    camera_before.is_motion_detected = False
    bootstrap_before["cameras"][camera_index]["lastMotion"] = to_js_time(camera_before.last_motion)
    bootstrap_before["cameras"][camera_index]["isMotionDetected"] = False
    bootstrap_before["lastUpdateId"] = expected_updated_id
    bootstrap = protect_client.bootstrap.unifi_dict()
    camera = get_camera()

    event = camera.last_motion_event
    camera.last_motion_event_id = None
    camera_before.last_motion_event_id = None

    assert bootstrap == bootstrap_before
    assert camera.dict() == camera_before.dict()
    assert event.id == expected_event_id
    assert event.type == EventType.MOTION
    assert event.thumbnail_id == f"e-{expected_event_id}"
    assert event.heatmap_id == f"e-{expected_event_id}"
    assert event.start == (now - timedelta(seconds=30))
    assert event.end == camera.last_motion


@pytest.mark.asyncio
@patch("pyunifiprotect.api.datetime", MockDatetime)
async def test_ws_event_smart(protect_client_no_debug: ProtectApiClient, now, camera, packet: WSPacket):
    protect_client = protect_client_no_debug

    def get_camera():
        return protect_client.bootstrap.cameras[camera["id"]]

    bootstrap_before = protect_client.bootstrap.unifi_dict()
    camera_before = get_camera().copy()

    expected_updated_id = "0441ecc6-f0fa-4b19-b071-7987c143138a"
    expected_event_id = "bf9a241afe74821ceffffd05"

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore
    action_frame.data["newUpdateId"] = expected_updated_id

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore
    data_frame.data = {
        "id": expected_event_id,
        "type": "smartDetectZone",
        "start": to_js_time(now - timedelta(seconds=30)),
        "end": to_js_time(now),
        "score": 0,
        "smartDetectTypes": ["person"],
        "smartDetectEvents": [],
        "camera": camera["id"],
        "partition": None,
        "user": None,
        "metadata": {},
        "thumbnail": f"e-{expected_event_id}",
        "heatmap": f"e-{expected_event_id}",
        "modelKey": "event",
    }

    msg = MagicMock()
    msg.data = packet.pack_frames()

    protect_client._process_ws_message(msg)

    camera_index = -1
    for index, camera_dict in enumerate(bootstrap_before["cameras"]):
        if camera_dict["id"] == camera["id"]:
            camera_index = index
            break

    camera_before.last_smart_detect = now
    bootstrap_before["cameras"][camera_index]["lastMotion"] = to_js_time(camera_before.last_motion)
    bootstrap_before["lastUpdateId"] = expected_updated_id
    bootstrap = protect_client.bootstrap.unifi_dict()
    camera = get_camera()

    smart_event = camera.last_smart_detect_event
    camera.last_smart_detect_event_id = None
    camera_before.last_smart_detect_event_id = None

    assert bootstrap == bootstrap_before
    assert camera.dict() == camera_before.dict()
    assert smart_event.id == expected_event_id
    assert smart_event.type == EventType.SMART_DETECT
    assert smart_event.thumbnail_id == f"e-{expected_event_id}"
    assert smart_event.heatmap_id == f"e-{expected_event_id}"
    assert smart_event.start == (now - timedelta(seconds=30))
    assert smart_event.end == now


@pytest.mark.asyncio
@patch("pyunifiprotect.api.datetime", MockDatetime)
async def test_ws_event_update(protect_client_no_debug: ProtectApiClient, now, camera, packet: WSPacket):
    protect_client = protect_client_no_debug

    def get_camera() -> Camera:
        return protect_client.bootstrap.cameras[camera["id"]]

    bootstrap_before = protect_client.bootstrap.unifi_dict()
    camera_before = get_camera().copy()

    new_stats = camera_before.stats.unifi_dict()
    new_stats["rxBytes"] += 100
    new_stats["txBytes"] += 100
    new_stats["video"]["recordingEnd"] = to_js_time(now)
    new_stats_unifi = camera_before.unifi_dict(data={"stats": deepcopy(new_stats)})

    del new_stats_unifi["stats"]["wifiQuality"]
    del new_stats_unifi["stats"]["wifiStrength"]

    expected_updated_id = "0441ecc6-f0fa-4b19-b071-7987c143138a"

    action_frame: WSJSONPacketFrame = packet.action_frame  # type: ignore
    action_frame.data = {
        "action": "update",
        "newUpdateId": expected_updated_id,
        "modelKey": "camera",
        "id": camera["id"],
    }

    data_frame: WSJSONPacketFrame = packet.data_frame  # type: ignore
    data_frame.data = new_stats_unifi

    msg = MagicMock()
    msg.data = packet.pack_frames()

    protect_client._process_ws_message(msg)

    camera_index = -1
    for index, camera_dict in enumerate(bootstrap_before["cameras"]):
        if camera_dict["id"] == camera["id"]:
            camera_index = index
            break

    bootstrap_before["cameras"][camera_index]["stats"] = new_stats
    bootstrap_before["lastUpdateId"] = expected_updated_id
    bootstrap = protect_client.bootstrap.unifi_dict()

    assert bootstrap == bootstrap_before
