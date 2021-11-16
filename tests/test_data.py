"""Tests for pyunifiprotect.data"""
# pylint: disable=protected-access

import base64
from copy import deepcopy
from typing import Optional, Set
from unittest.mock import Mock, patch

import pytest
from pytest_benchmark.fixture import BenchmarkFixture

from pyunifiprotect.data import (
    Bootstrap,
    Camera,
    Event,
    EventType,
    FixSizeOrderedDict,
    ModelType,
    WSPacket,
    create_from_unifi_dict,
)
from pyunifiprotect.exceptions import BadRequest, StreamError
from pyunifiprotect.utils import set_debug, set_no_debug
from tests.conftest import SAMPLE_DATA_DIRECTORY, MockTalkback, compare_objs

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


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_viewport.json").exists(), reason="No viewport in testdata")
def test_viewport(viewport):
    compare_devices(viewport)


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_light.json").exists(), reason="No light in testdata")
def test_light(light):
    compare_devices(light)


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_camera.json").exists(), reason="No camera in testdata")
def test_camera(camera):
    compare_devices(camera)


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_sensor.json").exists(), reason="No sensor in testdata")
def test_sensor(sensor):
    compare_devices(sensor)


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_bridge.json").exists(), reason="No bridge in testdata")
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
    del bootstrap["legacyUFVs"]
    del bootstrap["displays"]
    del bootstrap["doorlocks"]
    del bootstrap["chimes"]
    del bootstrap["schedules"]
    del bootstrap["nvr"]["uiVersion"]
    del bootstrap["nvr"]["errorCode"]
    del bootstrap["nvr"]["wifiSettings"]
    del bootstrap["nvr"]["ssoChannel"]
    del bootstrap["nvr"]["smartDetectAgreement"]
    del bootstrap["nvr"]["doorbellSettings"]["customMessages"]

    for model_type in ModelType.bootstrap_models():
        key = model_type + "s"
        expected_data = bootstrap.pop(key)
        actual_data = obj_dict.pop(key)

        assert len(expected_data) == len(actual_data)

        for index, expected in enumerate(expected_data):
            actual = actual_data[index]
            compare_objs(expected["modelKey"], expected, actual)

    assert bootstrap == obj_dict
    assert obj == obj_construct


def test_bootstrap_benchmark(bootstrap, benchmark: BenchmarkFixture):
    def create():
        Bootstrap.from_unifi_dict(**deepcopy(bootstrap))

    benchmark.pedantic(create, rounds=50, iterations=5)


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
    assert mock_instance.run_until_complete.called
    assert not mock_instance.get_errors.called


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
    assert mock_instance.get_errors.called


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
