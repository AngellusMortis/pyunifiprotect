"""Tests for pyunifiprotect.data"""
# pylint: disable=protected-access

import asyncio
import base64
from copy import deepcopy
from ipaddress import IPv4Address
from typing import Any, Dict, Optional, Set
from unittest.mock import Mock, patch

import pytest
from pytest_benchmark.fixture import BenchmarkFixture

from pyunifiprotect import ProtectApiClient
from pyunifiprotect.data import (
    Bootstrap,
    Camera,
    DoorbellMessageType,
    Event,
    EventType,
    FixSizeOrderedDict,
    ModelType,
    Permission,
    RecordingMode,
    StorageType,
    User,
    VideoMode,
    WSPacket,
    create_from_unifi_dict,
)
from pyunifiprotect.data.devices import LCDMessage
from pyunifiprotect.data.types import RecordingType, ResolutionStorageType
from pyunifiprotect.exceptions import BadRequest, NotAuthorized, StreamError
from pyunifiprotect.utils import set_debug, set_no_debug
from tests.conftest import (
    TEST_BRIDGE_EXISTS,
    TEST_CAMERA_EXISTS,
    TEST_DOORLOCK_EXISTS,
    TEST_LIGHT_EXISTS,
    TEST_SENSOR_EXISTS,
    TEST_VIEWPORT_EXISTS,
    MockTalkback,
    compare_objs,
)

PACKET_B64 = "AQEBAAAAAHR4nB2MQQrCMBBFr1JmbSDNpJnRG4hrDzBNZqCgqUiriHh3SZb/Pd7/guRtWSucBtgfRTaFwwBV39c+zqUJskQW1DufUVwkJsfFxDGLyRFj0dSz+1r0dtFPa+rr2dDSD8YsyceUpskQxzjjHIIQMvz+hMoj/AIBAQAAAAA1eJyrViotKMnMTVWyUjA0MjawMLQ0MDDQUVDKSSwuCU5NzQOJmxkbACUszE0sLQ1rAVU/DPU="
PACKET_ACTION = {
    "action": "update",
    "newUpdateId": "7f67f2e0-0c3a-4787-8dfa-88afa934de6e",
    "modelKey": "nvr",
    "id": "1ca6046655f3314b3b22a738",
}
PACKET_DATA = {"uptime": 1230819000, "lastSeen": 1630081874991}

PACKET2_B64 = "AQEBAAAAAHZ4nB2MQQrDMAwEvxJ0rqGxFNnuD0rOfYBsyRBoklISSij9e3GOO8PsF6Rs07rArYP9pbIZXDpY7PM4x12bSNdMGhkdZZ8dBakusanLHHmoojwQt2xe1Z6jHa0pMttbGp3OD0JDid7YY/VYrPfWhxQEfn/qpCUVAgEBAAAAATl4nHWQzU7DMBCEXwX5jJD/1nE5grjBoeoTuMk2tTBOsB2gqvLuOA5NaRE369vZ8cweSUwmRXJ/cyTh6+GQcHqDWEkQWt3ekLRALkAJpfhKZvxpd7Ys1XvjPbr89oNzebIL+D6grw9n5Kx/3fSIzcu2j2ccbeuNWw/G2TSpgS5wkwL6Nu0zpWOmW5MShkP5scdQo0+mxbOVjY97E1rr28x2xkWcrBxiv8n1JiFpbKy7HLVO2JDJ88M22M3Fse5Ck5ezOKSMWG4JTIKirLRdBE++KWPBGVWgKg4X47L/vD450KyoKIMrhx/B7KE5V+XO9g2d6SP+l2ERXGTgigum/+yfMlRAtZJUU3rl8CuDkBqUVNNJYurCfNcjGSJO//A8ZCA4MF2qztcUtLrjq4prClBVQo7j+A3Be62W"
PACKET2_ACTION = {
    "action": "update",
    "newUpdateId": "90b4d863-4b2b-47af-96ed-b6865fad6546",
    "modelKey": "camera",
    "id": "43e3a82e623f23ce12e1797a",
}
PACKET2_DATA = {
    "stats": {
        "rxBytes": 53945386,
        "txBytes": 2356366294,
        "wifi": {"channel": None, "frequency": None, "linkSpeedMbps": None, "signalQuality": 50, "signalStrength": 0},
        "battery": {"percentage": None, "isCharging": False, "sleepState": "disconnected"},
        "video": {
            "recordingStart": 1629514560194,
            "recordingEnd": 1632106567254,
            "recordingStartLQ": 1629505677015,
            "recordingEndLQ": 1632106582266,
            "timelapseStart": 1629514560194,
            "timelapseEnd": 1632106262318,
            "timelapseStartLQ": 1627508640800,
            "timelapseEndLQ": 1632103485646,
        },
        "storage": {"used": 285615325184, "rate": 307.297280557734},
    }
}


def test_packet_decode():
    packet_raw = base64.b64decode(PACKET_B64)

    packet = WSPacket(packet_raw)

    assert packet.raw == packet_raw
    assert packet.raw_base64 == PACKET_B64
    assert packet.action_frame.data == PACKET_ACTION
    assert packet.data_frame.data == PACKET_DATA


def test_packet_raw_setter():
    packet_raw = base64.b64decode(PACKET_B64)
    packet2_raw = base64.b64decode(PACKET2_B64)

    packet = WSPacket(packet_raw)
    packet.raw = packet2_raw

    assert packet.raw == packet2_raw
    assert packet.raw_base64 == PACKET2_B64
    assert packet.action_frame.data == PACKET2_ACTION
    assert packet.data_frame.data == PACKET2_DATA


def compare_devices(data):
    obj = create_from_unifi_dict(deepcopy(data))
    obj_dict = obj.unifi_dict()
    compare_objs(obj.model.value, data, obj_dict)

    set_no_debug()
    obj_construct = create_from_unifi_dict(deepcopy(data))
    assert obj == obj_construct
    set_debug()


@pytest.mark.skipif(not TEST_VIEWPORT_EXISTS, reason="Missing testdata")
def test_viewport(viewport):
    compare_devices(viewport)


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
def test_light(light):
    compare_devices(light)


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
def test_camera(camera):
    compare_devices(camera)


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
def test_sensor(sensor):
    compare_devices(sensor)


@pytest.mark.skipif(not TEST_DOORLOCK_EXISTS, reason="Missing testdata")
def test_doorlock(doorlock):
    compare_devices(doorlock)


@pytest.mark.skipif(not TEST_BRIDGE_EXISTS, reason="Missing testdata")
def test_bridge(bridge):
    compare_devices(bridge)


def test_events(raw_events):
    for event in raw_events:
        compare_devices(event)


def test_bootstrap(bootstrap):
    obj = Bootstrap.from_unifi_dict(**deepcopy(bootstrap))

    set_no_debug()
    obj_construct = Bootstrap.from_unifi_dict(**deepcopy(bootstrap))
    set_debug()

    obj_dict = obj.unifi_dict()

    # TODO:
    if "deviceGroups" in bootstrap:  # added in 2.0-beta
        del bootstrap["deviceGroups"]
    del bootstrap["legacyUFVs"]
    del bootstrap["displays"]
    del bootstrap["schedules"]
    if "deviceGroups" in bootstrap:
        del bootstrap["deviceGroups"]

    for model_type in ModelType.bootstrap_models():
        key = model_type + "s"
        expected_data = bootstrap.pop(key)
        actual_data = obj_dict.pop(key)

        assert len(expected_data) == len(actual_data)

        for index, expected in enumerate(expected_data):
            actual = actual_data[index]
            compare_objs(expected["modelKey"], expected, actual)

    compare_objs(ModelType.NVR.value, bootstrap.pop("nvr"), obj_dict.pop("nvr"))

    assert bootstrap == obj_dict
    assert obj == obj_construct


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
def test_bootstrap_device_not_adopted(bootstrap, protect_client: ProtectApiClient):
    bootstrap["cameras"][0]["isAdopted"] = False
    obj: Bootstrap = Bootstrap.from_unifi_dict(**deepcopy(bootstrap), api=protect_client)

    set_no_debug()
    obj_construct: Bootstrap = Bootstrap.from_unifi_dict(**deepcopy(bootstrap), api=protect_client)
    set_debug()

    expected_count = sum(1 if c["isAdopted"] else 0 for c in bootstrap["cameras"])
    assert len(obj.cameras) == expected_count
    assert obj.cameras == obj_construct.cameras


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
def test_bootstrap_device_not_adopted_no_api(bootstrap):
    bootstrap["cameras"][0]["isAdopted"] = False
    obj = Bootstrap.from_unifi_dict(**deepcopy(bootstrap))

    set_no_debug()
    obj_construct: Bootstrap = Bootstrap.from_unifi_dict(**deepcopy(bootstrap))
    set_debug()

    assert len(obj.cameras) == len(bootstrap["cameras"])
    assert obj.cameras == obj_construct.cameras


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
def test_bootstrap_device_not_adopted_enabled(bootstrap, protect_client: ProtectApiClient):
    bootstrap["cameras"][0]["isAdopted"] = False
    protect_client.ignore_unadopted = False
    obj: Bootstrap = Bootstrap.from_unifi_dict(**deepcopy(bootstrap), api=protect_client)

    set_no_debug()
    obj_construct: Bootstrap = Bootstrap.from_unifi_dict(**deepcopy(bootstrap), api=protect_client)
    set_debug()

    assert len(obj.cameras) == len(bootstrap["cameras"])
    assert obj.cameras == obj_construct.cameras


@pytest.mark.benchmark(group="construct")
@pytest.mark.timeout(0)
def test_bootstrap_benchmark(bootstrap, benchmark: BenchmarkFixture):
    def create():
        Bootstrap.from_unifi_dict(**deepcopy(bootstrap))

    benchmark.pedantic(create, rounds=50, iterations=5)


@pytest.mark.benchmark(group="construct")
@pytest.mark.timeout(0)
def test_bootstrap_benchmark_construct(bootstrap, benchmark: BenchmarkFixture):
    set_no_debug()

    def create():
        Bootstrap.from_unifi_dict(**deepcopy(bootstrap))

    benchmark.pedantic(create, rounds=50, iterations=5)
    set_debug()


def test_fix_order_size_dict_no_max():
    d = FixSizeOrderedDict()
    d["test"] = 1
    d["test2"] = 2
    d["test3"] = 3

    del d["test2"]

    assert d == {"test": 1, "test3": 3}


def test_fix_order_size_dict_max():
    d = FixSizeOrderedDict(max_size=1)
    d["test"] = 1
    d["test2"] = 2
    d["test3"] = 3

    with pytest.raises(KeyError):
        del d["test2"]

    assert d == {"test3": 3}


def test_fix_order_size_dict_negative_max():
    d = FixSizeOrderedDict(max_size=-1)
    d["test"] = 1
    d["test2"] = 2
    d["test3"] = 3

    del d["test2"]

    assert d == {"test": 1, "test3": 3}


def test_case_str_enum():
    assert RecordingMode("always") == RecordingMode.ALWAYS
    assert ResolutionStorageType("4K") == ResolutionStorageType.UHD
    assert VideoMode("highFps") == VideoMode.HIGH_FPS
    assert RecordingType("roTating") == RecordingType.CONTINUOUS


@pytest.mark.asyncio
async def test_play_audio_no_speaker(camera_obj: Camera):
    camera_obj.feature_flags.has_speaker = False
    camera_obj._initial_data = camera_obj.dict()

    with pytest.raises(BadRequest):
        await camera_obj.play_audio("test")


@pytest.mark.asyncio
@pytest.mark.usefixtures("disable_camera_validation")
async def test_play_audio_already_playing(camera_obj: Camera):
    camera_obj.feature_flags.has_speaker = True
    camera_obj._initial_data = camera_obj.dict()

    camera_obj.talkback_stream = Mock()
    camera_obj.talkback_stream.is_running = True

    with pytest.raises(BadRequest):
        await camera_obj.play_audio("test")


@pytest.mark.asyncio
@pytest.mark.usefixtures("disable_camera_validation")
@patch("pyunifiprotect.data.devices.TalkbackStream")
async def test_play_audio(mock_talkback, camera_obj: Camera):
    camera_obj.feature_flags.has_speaker = True
    camera_obj._initial_data = camera_obj.dict()

    mock_instance = MockTalkback()
    mock_talkback.return_value = mock_instance

    await camera_obj.play_audio("test")

    mock_talkback.assert_called_with(camera_obj, "test", None)
    assert mock_instance.start.called
    assert mock_instance.run_until_complete.called


@pytest.mark.asyncio
@pytest.mark.usefixtures("disable_camera_validation")
@patch("pyunifiprotect.data.devices.TalkbackStream")
async def test_play_audio_no_blocking(mock_talkback, camera_obj: Camera):
    camera_obj.feature_flags.has_speaker = True
    camera_obj._initial_data = camera_obj.dict()

    mock_instance = MockTalkback()
    mock_talkback.return_value = mock_instance

    await camera_obj.play_audio("test", blocking=False)

    mock_talkback.assert_called_with(camera_obj, "test", None)
    assert mock_instance.start.called
    assert not mock_instance.run_until_complete.called

    await camera_obj.wait_until_audio_completes()
    assert mock_instance.run_until_complete.called


@pytest.mark.asyncio
@pytest.mark.usefixtures("disable_camera_validation")
@patch("pyunifiprotect.data.devices.TalkbackStream")
async def test_play_audio_stop(mock_talkback, camera_obj: Camera):
    camera_obj.feature_flags.has_speaker = True
    camera_obj._initial_data = camera_obj.dict()

    mock_instance = MockTalkback()
    mock_talkback.return_value = mock_instance

    await camera_obj.play_audio("test", blocking=False)

    mock_talkback.assert_called_with(camera_obj, "test", None)
    assert mock_instance.start.called
    assert not mock_instance.run_until_complete.called

    await camera_obj.stop_audio()
    assert mock_instance.stop.called


@pytest.mark.asyncio
@pytest.mark.usefixtures("disable_camera_validation")
@patch("pyunifiprotect.data.devices.TalkbackStream")
async def test_play_audio_error(mock_talkback, camera_obj: Camera):
    camera_obj.feature_flags.has_speaker = True
    camera_obj._initial_data = camera_obj.dict()

    mock_instance = MockTalkback()
    mock_instance.is_error = True
    mock_talkback.return_value = mock_instance

    with pytest.raises(StreamError):
        await camera_obj.play_audio("test")

    mock_talkback.assert_called_with(camera_obj, "test", None)
    assert mock_instance.run_until_complete.called


@pytest.mark.asyncio
async def test_get_smart_detect_track_bad_type(smart_dectect_obj: Optional[Event]):
    if smart_dectect_obj is None:
        pytest.skip("No smart detection object found")

    smart_dectect_obj.type = EventType.MOTION

    with pytest.raises(BadRequest):
        await smart_dectect_obj.get_smart_detect_track()


@pytest.mark.asyncio
async def test_get_smart_detect_track(smart_dectect_obj: Optional[Event]):
    if smart_dectect_obj is None:
        pytest.skip("No smart detection object found")

    track = await smart_dectect_obj.get_smart_detect_track()
    assert track.camera


@pytest.mark.asyncio
async def test_get_smart_detect_zones(smart_dectect_obj: Optional[Event]):
    if smart_dectect_obj is None:
        pytest.skip("No smart detection object found")

    camera = smart_dectect_obj.camera
    if camera is None:
        pytest.skip("Camera not found for smart detection")

    track = await smart_dectect_obj.get_smart_detect_track()
    zone_ids: Set[int] = set()
    for item in track.payload:
        zone_ids = zone_ids | set(item.zone_ids)

    zones = await smart_dectect_obj.get_smart_detect_zones()
    for zone_id, zone in zones.items():
        assert zone_id in zone_ids
        assert zone_id == zone.id
        assert zone in camera.smart_detect_zones


def test_doorbell_bad_state():
    message = LCDMessage.from_unifi_dict(text="Test")

    assert message.text == "Test"
    assert message.type == DoorbellMessageType.CUSTOM_MESSAGE


def test_camera_ip_host(camera):
    camera["host"] = "1.1.1.1"
    camera["connectionHost"] = "1.1.1.1"

    camera_obj = Camera.from_unifi_dict(**camera)
    assert camera_obj.host == IPv4Address("1.1.1.1")
    assert camera_obj.connection_host == IPv4Address("1.1.1.1")


def test_camera_dns_host(camera):
    camera["host"] = "se-gw.local"
    camera["connectionHost"] = "se-gw.local"

    camera_obj = Camera.from_unifi_dict(**camera)
    assert camera_obj.host == "se-gw.local"
    assert camera_obj.connection_host == "se-gw.local"


def test_bootstrap_ip_host(bootstrap):
    bootstrap["nvr"]["hosts"] = ["1.1.1.1"]

    bootstrap_obj = Bootstrap.from_unifi_dict(**bootstrap)
    assert bootstrap_obj.nvr.hosts == [IPv4Address("1.1.1.1")]


def test_bootstrap_dns_host(bootstrap):
    bootstrap["nvr"]["hosts"] = ["se-gw.local"]

    bootstrap_obj = Bootstrap.from_unifi_dict(**bootstrap)
    assert bootstrap_obj.nvr.hosts == ["se-gw.local"]


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_save_device_no_changes(camera_obj: Camera):
    camera_obj.api.api_request.reset_mock()  # type: ignore

    await camera_obj.save_device()

    assert not camera_obj.api.api_request.called  # type: ignore


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_device_reboot(camera_obj: Camera):
    camera_obj.api.api_request.reset_mock()  # type: ignore

    await camera_obj.reboot()

    camera_obj.api.api_request.assert_called_with(  # type: ignore
        f"cameras/{camera_obj.id}/reboot",
        method="post",
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(
    "permissions,can_create,can_read,can_write,can_delete,can_read_media,can_delete_media",
    [
        (["camera:*:*"], True, True, True, True, True, True),
        (["camera:create,read,write,delete,readmedia,deletemedia:*"], True, True, True, True, True, True),
        (["camera:create,read,write,readmedia:*"], True, True, True, False, True, False),
        (["camera:read,readmedia:*"], False, True, False, False, True, False),
        (["camera:read,readmedia:test_id_1,test_id_2"], False, True, False, False, True, False),
        (["camera:read,readmedia:test_id_2,test_id_1"], False, True, False, False, True, False),
        (["camera:delete:test_id_1", "camera:read,readmedia:*"], False, True, False, True, True, False),
        (["camera:delete:test_id_2", "camera:read,readmedia:*"], False, True, False, False, True, False),
        (["camera:read,readmedia:*", "camera:delete:test_id_1"], False, True, False, True, True, False),
        (["camera:read,readmedia:*", "camera:delete:test_id_2"], False, True, False, False, True, False),
    ],
)
@pytest.mark.asyncio
async def test_permissions(
    user_obj: User,
    camera_obj: Camera,
    permissions: list[str],
    can_create: bool,
    can_read: bool,
    can_write: bool,
    can_delete: bool,
    can_read_media: bool,
    can_delete_media: bool,
):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    api = user_obj.api
    user_obj.all_permissions = [Permission.from_unifi_dict(rawPermission=p, api=api) for p in permissions]
    user_obj._initial_data = user_obj.dict()
    camera_obj.id = "test_id_1"
    camera_obj._initial_data = camera_obj.dict()
    api.bootstrap.cameras[camera_obj.id] = camera_obj

    assert camera_obj.can_create(user_obj) is can_create
    assert camera_obj.can_read(user_obj) is can_read
    assert camera_obj.can_write(user_obj) is can_write
    assert camera_obj.can_delete(user_obj) is can_delete
    assert camera_obj.can_read_media(user_obj) is can_read_media
    assert camera_obj.can_delete_media(user_obj) is can_delete_media


@pytest.mark.parametrize(
    "permissions,can_create,can_read,can_write,can_delete",
    [
        (["user:*:*"], True, True, True, True),
        (["user:create,read,write,delete:*"], True, True, True, True),
        (["user:create,read,write,delete:$"], True, True, True, True),
        (["user:read,write:$", "user:create,read,write,delete:*"], True, True, True, True),
        (["user:read,write:*"], False, True, True, False),
        (["user:read,write:$"], False, True, True, False),
        (["user:read,write:$", "user:create,read,write,delete:test_id_2"], False, True, True, False),
        (["user:create,delete:$", "user:read,write:*"], True, True, True, True),
    ],
)
@pytest.mark.asyncio
async def test_permissions_user(
    user_obj: User,
    permissions: list[str],
    can_create: bool,
    can_read: bool,
    can_write: bool,
    can_delete: bool,
):
    api = user_obj.api

    user1 = user_obj.copy()
    user1.id = "test_id_1"
    user1.all_permissions = [Permission.from_unifi_dict(rawPermission=p, api=api) for p in permissions]
    user1._initial_data = user1.dict()

    api.bootstrap.auth_user_id = user1.id
    api.bootstrap.users = {user1.id: user1}

    assert user1.can_create(user1) is can_create
    assert user1.can_read(user1) is can_read
    assert user1.can_write(user1) is can_write
    assert user1.can_delete(user1) is can_delete


@pytest.mark.parametrize(
    "permissions,can_create,can_read,can_write,can_delete",
    [
        (["user:*:*"], True, True, True, True),
        (["user:create,read,write,delete:*"], True, True, True, True),
        (["user:create,read,write,delete:$"], False, False, False, False),
        (["user:read,write:$", "user:create,read,write,delete:*"], True, True, True, True),
        (["user:read,write:*"], False, True, True, False),
        (["user:read,write:$"], False, False, False, False),
        (["user:read,write:$", "user:create,read,write,delete:test_id_2"], True, True, True, True),
        (["user:create,delete:$", "user:read,write:*"], False, True, True, False),
    ],
)
@pytest.mark.asyncio
async def test_permissions_self_with_other(
    user_obj: User,
    permissions: list[str],
    can_create: bool,
    can_read: bool,
    can_write: bool,
    can_delete: bool,
):
    api = user_obj.api

    user1 = user_obj.copy()
    user1.id = "test_id_1"
    user1.all_permissions = [Permission.from_unifi_dict(rawPermission=p, api=api) for p in permissions]
    user1._initial_data = user1.dict()

    user2 = user_obj.copy()
    user2.id = "test_id_2"
    user2._initial_data = user2.dict()

    api.bootstrap.auth_user_id = user1.id
    api.bootstrap.users = {user1.id: user1, user2.id: user2}

    assert user2.can_create(user1) is can_create
    assert user2.can_read(user1) is can_read
    assert user2.can_write(user1) is can_write
    assert user2.can_delete(user1) is can_delete


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_revert(user_obj: User, camera_obj: Camera):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    api = user_obj.api
    camera_obj.id = "test_id_1"
    camera_obj.add_privacy_zone()
    camera_obj.recording_settings.mode = RecordingMode.NEVER
    camera_obj._initial_data = camera_obj.dict()
    api.bootstrap.cameras[camera_obj.id] = camera_obj

    user_obj.all_permissions = [Permission.from_unifi_dict(rawPermission="camera:read:*", api=api)]
    user_obj._initial_data = user_obj.dict()

    camera_before = camera_obj.dict()

    camera_obj.remove_privacy_zone()
    camera_obj.recording_settings.mode = RecordingMode.ALWAYS
    with pytest.raises(NotAuthorized):
        await camera_obj.save_device()

    assert camera_before == camera_obj.dict()


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_multiple_updates(user_obj: User, camera_obj: Camera):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    api = user_obj.api
    camera_obj.id = "test_id_1"
    camera_obj.recording_settings.enable_motion_detection = False
    camera_obj.smart_detect_settings.object_types = []
    camera_obj._initial_data = camera_obj.dict()
    api.bootstrap.cameras[camera_obj.id] = camera_obj

    await asyncio.gather(
        camera_obj.set_motion_detection(True),
        camera_obj.set_person_detection(True),
        camera_obj.set_vehicle_detection(True),
    )

    camera_obj.api.api_request.assert_called_with(  # type: ignore
        f"cameras/{camera_obj.id}",
        method="patch",
        json={
            "recordingSettings": {"enableMotionDetection": True},
            "smartDetectSettings": {"objectTypes": ["person", "vehicle"]},
        },
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
def test_unknown_smart(camera: Optional[Dict[str, Any]], bootstrap: Dict[str, Any], protect_client: ProtectApiClient):
    if camera is None:
        pytest.skip("No camera obj found")

    camera["featureFlags"]["smartDetectTypes"] = ["alrmSmoke"]
    camera["smartDetectZones"][0]["objectTypes"] = ["alrmSmoke"]
    camera["smartDetectSettings"]["objectTypes"] = ["alrmSmoke"]
    bootstrap["cameras"] = [camera]

    obj: Bootstrap = Bootstrap.from_unifi_dict(**deepcopy(bootstrap), api=protect_client)
    camera_obj = list(obj.cameras.values())[0]
    assert camera_obj.feature_flags.smart_detect_types == []
    assert camera_obj.smart_detect_zones[0].object_types == []
    assert camera_obj.smart_detect_settings.object_types == []

    set_no_debug()
    obj: Bootstrap = Bootstrap.from_unifi_dict(**deepcopy(bootstrap), api=protect_client)
    camera_obj = list(obj.cameras.values())[0]
    assert camera_obj.feature_flags.smart_detect_types == []
    assert camera_obj.smart_detect_zones[0].object_types == []
    assert camera_obj.smart_detect_settings.object_types == []
    set_debug()


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
def test_unknown_video(camera: Optional[Dict[str, Any]], bootstrap: Dict[str, Any], protect_client: ProtectApiClient):
    if camera is None:
        pytest.skip("No camera obj found")

    camera["featureFlags"]["videoModes"] = ["stuff"]
    bootstrap["cameras"] = [camera]

    obj: Bootstrap = Bootstrap.from_unifi_dict(**deepcopy(bootstrap), api=protect_client)
    camera_obj = list(obj.cameras.values())[0]
    assert camera_obj.feature_flags.video_modes == []

    set_no_debug()
    obj: Bootstrap = Bootstrap.from_unifi_dict(**deepcopy(bootstrap), api=protect_client)
    camera_obj = list(obj.cameras.values())[0]
    assert camera_obj.feature_flags.video_modes == []
    set_debug()


def test_unknown_storage_type(bootstrap: Dict[str, Any], protect_client: ProtectApiClient):
    bootstrap["nvr"]["systemInfo"]["storage"]["type"] = "test"

    obj: Bootstrap = Bootstrap.from_unifi_dict(**deepcopy(bootstrap), api=protect_client)
    assert obj.nvr.system_info.storage.type == StorageType.UNKNOWN

    set_no_debug()
    obj: Bootstrap = Bootstrap.from_unifi_dict(**deepcopy(bootstrap), api=protect_client)
    assert obj.nvr.system_info.storage.type == StorageType.UNKNOWN
    set_debug()
