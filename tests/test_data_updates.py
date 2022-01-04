# type: ignore
# pylint: disable=protected-access

from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import Mock, patch

from pydantic.error_wrappers import ValidationError
import pytest

from pyunifiprotect.data import (
    Camera,
    DoorbellMessageType,
    IRLEDMode,
    LCDMessage,
    Light,
    Liveview,
    RecordingMode,
    VideoMode,
    Viewer,
)
from pyunifiprotect.data.devices import CameraZone, Sensor
from pyunifiprotect.data.nvr import NVR, DoorbellMessage
from pyunifiprotect.data.types import (
    DEFAULT,
    LightModeEnableType,
    LightModeType,
    MountType,
    SmartDetectObjectType,
)
from pyunifiprotect.data.websocket import WSAction, WSSubscriptionMessage
from pyunifiprotect.exceptions import BadRequest
from pyunifiprotect.utils import to_js_time, to_ms
from tests.conftest import (
    TEST_CAMERA_EXISTS,
    TEST_LIGHT_EXISTS,
    TEST_SENSOR_EXISTS,
    TEST_VIEWPORT_EXISTS,
)


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_save_device_no_changes(camera_obj: Camera):
    camera_obj.api.api_request.reset_mock()

    await camera_obj.save_device()

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_device_reboot(camera_obj: Camera):
    camera_obj.api.api_request.reset_mock()

    await camera_obj.reboot()

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}/reboot",
        method="post",
    )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_light_set_paired_camera_none(light_obj: Light):
    light_obj.api.api_request.reset_mock()

    light_obj.camera_id = "bad_id"
    light_obj._initial_data = light_obj.dict()

    await light_obj.set_paired_camera(None)

    light_obj.api.api_request.assert_called_with(
        f"lights/{light_obj.id}",
        method="patch",
        json={"camera": None},
    )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS or not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_light_set_paired_camera(light_obj: Light, camera_obj: Camera):
    light_obj.api.api_request.reset_mock()

    light_obj.camera_id = None
    light_obj._initial_data = light_obj.dict()

    await light_obj.set_paired_camera(camera_obj)

    light_obj.api.api_request.assert_called_with(
        f"lights/{light_obj.id}",
        method="patch",
        json={"camera": camera_obj.id},
    )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_light_set_status_light(light_obj: Light, status: bool):
    light_obj.api.api_request.reset_mock()

    light_obj.light_device_settings.is_indicator_enabled = not status
    light_obj._initial_data = light_obj.dict()

    await light_obj.set_status_light(status)

    light_obj.api.api_request.assert_called_with(
        f"lights/{light_obj.id}",
        method="patch",
        json={"lightDeviceSettings": {"isIndicatorEnabled": status}},
    )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("level", [-1, 1, 3, 6, 7])
@pytest.mark.asyncio
async def test_light_set_led_level(light_obj: Light, level: int):
    light_obj.api.api_request.reset_mock()

    light_obj.light_device_settings.led_level = 2
    light_obj._initial_data = light_obj.dict()

    if level in (-1, 7):
        with pytest.raises(ValidationError):
            await light_obj.set_led_level(level)

            assert not light_obj.api.api_request.called
    else:
        await light_obj.set_led_level(level)

        light_obj.api.api_request.assert_called_with(
            f"lights/{light_obj.id}",
            method="patch",
            json={"lightDeviceSettings": {"ledLevel": level}},
        )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.parametrize("level", [None, -1, 1, 3, 6, 7])
@pytest.mark.asyncio
async def test_light_set_light(light_obj: Light, status: bool, level: Optional[int]):
    light_obj.api.api_request.reset_mock()

    light_obj.light_on_settings.is_led_force_on = not status
    if level is not None:
        light_obj.light_device_settings.led_level = 2
    light_obj._initial_data = light_obj.dict()

    if level in (-1, 7):
        with pytest.raises(ValidationError):
            await light_obj.set_light(status, level)

            assert not light_obj.api.api_request.called
    else:
        await light_obj.set_light(status, level)

        if level is None:
            expected = {"lightOnSettings": {"isLedForceOn": status}}
        else:
            expected = {"lightOnSettings": {"isLedForceOn": status}, "lightDeviceSettings": {"ledLevel": level}}

        light_obj.api.api_request.assert_called_with(
            f"lights/{light_obj.id}",
            method="patch",
            json=expected,
        )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("sensitivity", [1, 100, -10])
@pytest.mark.asyncio
async def test_light_set_sensitivity(
    light_obj: Light,
    sensitivity: int,
):
    light_obj.api.api_request.reset_mock()

    light_obj.light_device_settings.pir_sensitivity = 50
    light_obj._initial_data = light_obj.dict()

    if sensitivity == -10:
        with pytest.raises(ValidationError):
            await light_obj.set_sensitivity(sensitivity)

            assert not light_obj.api.api_request.called
    else:
        await light_obj.set_sensitivity(sensitivity)

        expected = {"lightDeviceSettings": {"pirSensitivity": sensitivity}}

        light_obj.api.api_request.assert_called_with(
            f"lights/{light_obj.id}",
            method="patch",
            json=expected,
        )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(
    "duration",
    [
        timedelta(seconds=1),
        timedelta(seconds=15),
        timedelta(seconds=900),
        timedelta(seconds=1000),
    ],
)
@pytest.mark.asyncio
async def test_light_set_duration(
    light_obj: Light,
    duration: timedelta,
):
    light_obj.api.api_request.reset_mock()

    light_obj.light_device_settings.pir_duration = timedelta(seconds=30)
    light_obj._initial_data = light_obj.dict()

    duration_invalid = duration is not None and int(duration.total_seconds()) in (1, 1000)
    if duration_invalid:
        with pytest.raises(BadRequest):
            await light_obj.set_duration(duration)

            assert not light_obj.api.api_request.called
    else:
        await light_obj.set_duration(duration)

        expected = {"lightDeviceSettings": {"pirDuration": to_ms(duration)}}

        light_obj.api.api_request.assert_called_with(
            f"lights/{light_obj.id}",
            method="patch",
            json=expected,
        )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("mode", [LightModeType.MANUAL, LightModeType.WHEN_DARK])
@pytest.mark.parametrize("enable_at", [None, LightModeEnableType.ALWAYS])
@pytest.mark.parametrize(
    "duration",
    [
        None,
        timedelta(seconds=1),
        timedelta(seconds=15),
        timedelta(seconds=900),
        timedelta(seconds=1000),
    ],
)
@pytest.mark.parametrize("sensitivity", [None, 1, 100, -10])
@pytest.mark.asyncio
async def test_light_set_light_settings(
    light_obj: Light,
    mode: LightModeType,
    enable_at: Optional[LightModeEnableType],
    duration: Optional[timedelta],
    sensitivity: Optional[int],
):
    light_obj.api.api_request.reset_mock()

    light_obj.light_mode_settings.mode = LightModeType.MOTION
    light_obj.light_mode_settings.enable_at = LightModeEnableType.DARK
    light_obj.light_device_settings.pir_duration = timedelta(seconds=30)
    light_obj.light_device_settings.pir_sensitivity = 50
    light_obj._initial_data = light_obj.dict()

    duration_invalid = duration is not None and int(duration.total_seconds()) in (1, 1000)
    if duration_invalid:
        with pytest.raises(BadRequest):
            await light_obj.set_light_settings(mode, enable_at=enable_at, duration=duration, sensitivity=sensitivity)

            assert not light_obj.api.api_request.called
    elif sensitivity == -10:
        with pytest.raises(ValidationError):
            await light_obj.set_light_settings(mode, enable_at=enable_at, duration=duration, sensitivity=sensitivity)

            assert not light_obj.api.api_request.called
    else:
        await light_obj.set_light_settings(mode, enable_at=enable_at, duration=duration, sensitivity=sensitivity)

        expected = {"lightModeSettings": {"mode": mode.value}}
        if enable_at is not None:
            expected["lightModeSettings"].update({"enableAt": enable_at.value})
        if duration is not None:
            expected["lightDeviceSettings"] = expected.get("lightDeviceSettings", {})
            expected["lightDeviceSettings"].update({"pirDuration": to_ms(duration)})
        if sensitivity is not None:
            expected["lightDeviceSettings"] = expected.get("lightDeviceSettings", {})
            expected["lightDeviceSettings"].update({"pirSensitivity": sensitivity})

        light_obj.api.api_request.assert_called_with(
            f"lights/{light_obj.id}",
            method="patch",
            json=expected,
        )


@pytest.mark.skipif(not TEST_VIEWPORT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_viewer_set_liveview_invalid(viewer_obj: Viewer, liveview_obj: Liveview):
    viewer_obj.api.api_request.reset_mock()

    liveview = liveview_obj.update_from_dict({"id": "bad_id"})

    with pytest.raises(BadRequest):
        await viewer_obj.set_liveview(liveview)

    assert not viewer_obj.api.api_request.called


@pytest.mark.skipif(not TEST_VIEWPORT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_viewer_set_liveview_valid(viewer_obj: Viewer, liveview_obj: Liveview):
    viewer_obj.api.api_request.reset_mock()
    viewer_obj.api.emit_message = Mock()

    viewer_obj.liveview_id = "bad_id"
    viewer_obj._initial_data = viewer_obj.dict()

    await viewer_obj.set_liveview(liveview_obj)
    viewer_obj.api.api_request.assert_called_with(
        f"viewers/{viewer_obj.id}",
        method="patch",
        json={"liveview": liveview_obj.id},
    )

    # old/new is actually the same here since the client
    # generating the message is the one that changed it
    viewer_obj.api.emit_message.assert_called_with(
        WSSubscriptionMessage(
            action=WSAction.UPDATE,
            new_update_id=viewer_obj.api.bootstrap.last_update_id,
            changed_data={"liveview_id": liveview_obj.id},
            old_obj=viewer_obj,
            new_obj=viewer_obj,
        )
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("mode", [RecordingMode.ALWAYS, RecordingMode.DETECTIONS])
@pytest.mark.asyncio
async def test_camera_set_recording_mode(camera_obj: Optional[Camera], mode: RecordingMode):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.recording_settings.mode = RecordingMode.NEVER
    camera_obj._initial_data = camera_obj.dict()

    await camera_obj.set_recording_mode(mode)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"recordingSettings": {"mode": mode.value}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_camera_set_ir_led_model_no_ir(camera_obj: Optional[Camera]):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_led_ir = False
    camera_obj._initial_data = camera_obj.dict()

    with pytest.raises(BadRequest):
        await camera_obj.set_ir_led_model(IRLEDMode.AUTO)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("mode", [IRLEDMode.AUTO, IRLEDMode.ON])
@pytest.mark.asyncio
async def test_camera_set_ir_led_model(camera_obj: Optional[Camera], mode: IRLEDMode):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_led_ir = True
    camera_obj.isp_settings.ir_led_mode = IRLEDMode.OFF
    camera_obj._initial_data = camera_obj.dict()

    await camera_obj.set_ir_led_model(mode)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"ispSettings": {"irLedMode": mode.value}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_camera_set_status_light_no_status(camera_obj: Optional[Camera]):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_led_status = False
    camera_obj._initial_data = camera_obj.dict()

    with pytest.raises(BadRequest):
        await camera_obj.set_status_light(True)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_camera_set_status_light(camera_obj: Optional[Camera], status: bool):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_led_status = True
    camera_obj.led_settings.is_enabled = not status
    camera_obj.led_settings.blink_rate = 10
    camera_obj._initial_data = camera_obj.dict()

    await camera_obj.set_status_light(status)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"ledSettings": {"isEnabled": status, "blinkRate": 0}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_camera_set_hdr_no_hdr(camera_obj: Optional[Camera]):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_hdr = False
    camera_obj._initial_data = camera_obj.dict()

    with pytest.raises(BadRequest):
        await camera_obj.set_hdr(True)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_camera_set_hdr(camera_obj: Optional[Camera], status: bool):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_hdr = True
    camera_obj.hdr_mode = not status
    camera_obj._initial_data = camera_obj.dict()

    await camera_obj.set_hdr(status)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"hdrMode": status},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_camera_set_ssh(camera_obj: Optional[Camera], status: bool):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.is_ssh_enabled = not status
    camera_obj._initial_data = camera_obj.dict()

    await camera_obj.set_ssh(status)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"isSshEnabled": status},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_camera_set_video_mode_no_highfps(camera_obj: Optional[Camera]):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.video_modes = [VideoMode.DEFAULT]
    camera_obj.video_mode = VideoMode.DEFAULT
    camera_obj._initial_data = camera_obj.dict()

    with pytest.raises(BadRequest):
        await camera_obj.set_video_mode(VideoMode.HIGH_FPS)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_camera_set_video_mode(camera_obj: Optional[Camera]):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.video_modes = [VideoMode.DEFAULT, VideoMode.HIGH_FPS]
    camera_obj.video_mode = VideoMode.DEFAULT
    camera_obj._initial_data = camera_obj.dict()

    await camera_obj.set_video_mode(VideoMode.HIGH_FPS)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"videoMode": VideoMode.HIGH_FPS.value},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_camera_set_camera_zoom_no_zoom(camera_obj: Optional[Camera]):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.can_optical_zoom = False
    camera_obj._initial_data = camera_obj.dict()

    with pytest.raises(BadRequest):
        await camera_obj.set_camera_zoom(True)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("level", [-1, 0, 100, 200])
@pytest.mark.asyncio
async def test_camera_set_camera_zoom(camera_obj: Optional[Camera], level: int):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.can_optical_zoom = True
    camera_obj.isp_settings.zoom_position = 10
    camera_obj._initial_data = camera_obj.dict()

    if level in (-1, 200):
        with pytest.raises(ValidationError):
            await camera_obj.set_camera_zoom(level)

        assert not camera_obj.api.api_request.called
    else:
        await camera_obj.set_camera_zoom(level)

        camera_obj.api.api_request.assert_called_with(
            f"cameras/{camera_obj.id}",
            method="patch",
            json={"ispSettings": {"zoomPosition": level}},
        )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("level", [-1, 0, 3, 4])
@pytest.mark.asyncio
async def test_camera_set_wdr_level(camera_obj: Optional[Camera], level: int):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_hdr = False
    camera_obj.isp_settings.wdr = 2
    camera_obj._initial_data = camera_obj.dict()

    if level in (-1, 4):
        with pytest.raises(ValidationError):
            await camera_obj.set_wdr_level(level)

            assert not camera_obj.api.api_request.called
    else:
        await camera_obj.set_wdr_level(level)

        camera_obj.api.api_request.assert_called_with(
            f"cameras/{camera_obj.id}",
            method="patch",
            json={"ispSettings": {"wdr": level}},
        )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_camera_set_wdr_level_hdr(camera_obj: Optional[Camera]):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_hdr = True
    camera_obj._initial_data = camera_obj.dict()

    with pytest.raises(BadRequest):
        await camera_obj.set_wdr_level(1)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_camera_set_mic_volume_no_mic(camera_obj: Optional[Camera]):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_mic = False
    camera_obj._initial_data = camera_obj.dict()

    with pytest.raises(BadRequest):
        await camera_obj.set_mic_volume(True)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("level", [-1, 0, 100, 200])
@pytest.mark.asyncio
async def test_camera_set_mic_volume(camera_obj: Optional[Camera], level: int):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_mic = True
    camera_obj.mic_volume = 10
    camera_obj._initial_data = camera_obj.dict()

    if level in (-1, 200):
        with pytest.raises(ValidationError):
            await camera_obj.set_mic_volume(level)

        assert not camera_obj.api.api_request.called
    else:
        await camera_obj.set_mic_volume(level)

        camera_obj.api.api_request.assert_called_with(
            f"cameras/{camera_obj.id}",
            method="patch",
            json={"micVolume": level},
        )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_camera_set_speaker_volume_no_speaker(camera_obj: Optional[Camera]):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_speaker = False
    camera_obj._initial_data = camera_obj.dict()

    with pytest.raises(BadRequest):
        await camera_obj.set_speaker_volume(True)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("level", [-1, 0, 100, 200])
@pytest.mark.asyncio
async def test_camera_set_speaker_volume(camera_obj: Optional[Camera], level: int):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_speaker = True
    camera_obj.speaker_settings.volume = 10
    camera_obj._initial_data = camera_obj.dict()

    if level in (-1, 200):
        with pytest.raises(ValidationError):
            await camera_obj.set_speaker_volume(level)

        assert not camera_obj.api.api_request.called
    else:
        await camera_obj.set_speaker_volume(level)

        camera_obj.api.api_request.assert_called_with(
            f"cameras/{camera_obj.id}",
            method="patch",
            json={"speakerSettings": {"volume": level}},
        )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_camera_set_chime_duration_no_chime(camera_obj: Optional[Camera]):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_chime = False
    camera_obj._initial_data = camera_obj.dict()

    with pytest.raises(BadRequest):
        await camera_obj.set_chime_duration(1000)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("duration", [-1, 0, 5000, 10000, 20000])
@pytest.mark.asyncio
async def test_camera_set_chime_duration_duration(camera_obj: Optional[Camera], duration: int):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_chime = True
    camera_obj.chime_duration = 300
    camera_obj.mic_volume = 10
    camera_obj._initial_data = camera_obj.dict()

    if duration in (-1, 20000):
        with pytest.raises(ValidationError):
            await camera_obj.set_chime_duration(duration)

        assert not camera_obj.api.api_request.called
    else:
        await camera_obj.set_chime_duration(duration)

        camera_obj.api.api_request.assert_called_with(
            f"cameras/{camera_obj.id}",
            method="patch",
            json={"chimeDuration": duration},
        )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_camera_set_system_sounds_no_speaker(camera_obj: Optional[Camera]):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_speaker = False
    camera_obj._initial_data = camera_obj.dict()

    with pytest.raises(BadRequest):
        await camera_obj.set_system_sounds(True)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_camera_set_system_sounds(camera_obj: Optional[Camera], status: bool):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_speaker = True
    camera_obj.speaker_settings.are_system_sounds_enabled = not status
    camera_obj._initial_data = camera_obj.dict()

    await camera_obj.set_system_sounds(status)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"speakerSettings": {"areSystemSoundsEnabled": status}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_camera_set_osd_name(camera_obj: Optional[Camera], status: bool):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.osd_settings.is_name_enabled = not status
    camera_obj._initial_data = camera_obj.dict()

    await camera_obj.set_osd_name(status)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"osdSettings": {"isNameEnabled": status}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_camera_set_osd_date(camera_obj: Optional[Camera], status: bool):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.osd_settings.is_date_enabled = not status
    camera_obj._initial_data = camera_obj.dict()

    await camera_obj.set_osd_date(status)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"osdSettings": {"isDateEnabled": status}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_camera_set_osd_logo(camera_obj: Optional[Camera], status: bool):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.osd_settings.is_logo_enabled = not status
    camera_obj._initial_data = camera_obj.dict()

    await camera_obj.set_osd_logo(status)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"osdSettings": {"isLogoEnabled": status}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_camera_set_osd_bitrate(camera_obj: Optional[Camera], status: bool):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.osd_settings.is_debug_enabled = not status
    camera_obj._initial_data = camera_obj.dict()

    await camera_obj.set_osd_bitrate(status)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"osdSettings": {"isDebugEnabled": status}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_camera_set_smart_detect_types_no_smart(camera_obj: Optional[Camera]):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_smart_detect = False
    camera_obj._initial_data = camera_obj.dict()

    with pytest.raises(BadRequest):
        await camera_obj.set_smart_detect_types([])

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_camera_set_smart_detect_types(camera_obj: Optional[Camera]):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_smart_detect = True
    camera_obj.smart_detect_settings.object_types = []
    camera_obj._initial_data = camera_obj.dict()

    await camera_obj.set_smart_detect_types([SmartDetectObjectType.PERSON])

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"smartDetectSettings": {"objectTypes": ["person"]}},
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_camera_set_lcd_text_no_lcd(camera_obj: Optional[Camera]):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_lcd_screen = False
    camera_obj._initial_data = camera_obj.dict()

    with pytest.raises(BadRequest):
        await camera_obj.set_lcd_text(DoorbellMessageType.DO_NOT_DISTURB)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_camera_set_lcd_text_custom(camera_obj: Optional[Camera]):

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_lcd_screen = True
    camera_obj.lcd_message = LCDMessage(
        type=DoorbellMessageType.DO_NOT_DISTURB,
        text=DoorbellMessageType.DO_NOT_DISTURB.value.replace("_", " "),
        reset_at=None,
    )
    camera_obj._initial_data = camera_obj.dict()

    now = datetime.utcnow()
    await camera_obj.set_lcd_text(DoorbellMessageType.CUSTOM_MESSAGE, "Test", now)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={
            "lcdMessage": {
                "type": DoorbellMessageType.CUSTOM_MESSAGE.value,
                "text": "Test",
                "resetAt": to_js_time(now),
            }
        },
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_camera_set_lcd_text_custom_to_custom(camera_obj: Optional[Camera]):

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_lcd_screen = True
    camera_obj.lcd_message = LCDMessage(
        type=DoorbellMessageType.CUSTOM_MESSAGE,
        text="Welcome",
        reset_at=None,
    )
    camera_obj._initial_data = camera_obj.dict()

    now = datetime.utcnow()
    await camera_obj.set_lcd_text(DoorbellMessageType.CUSTOM_MESSAGE, "Test", now)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={
            "lcdMessage": {
                "type": DoorbellMessageType.CUSTOM_MESSAGE.value,
                "text": "Test",
                "resetAt": to_js_time(now),
            }
        },
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_camera_set_lcd_text_invalid_text(camera_obj: Optional[Camera]):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_lcd_screen = True
    camera_obj._initial_data = camera_obj.dict()

    with pytest.raises(BadRequest):
        await camera_obj.set_lcd_text(DoorbellMessageType.DO_NOT_DISTURB, "Test")

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_camera_set_lcd_text(camera_obj: Optional[Camera]):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_lcd_screen = True
    camera_obj.lcd_message = LCDMessage(
        type=DoorbellMessageType.DO_NOT_DISTURB,
        text=DoorbellMessageType.DO_NOT_DISTURB.value.replace("_", " "),
        reset_at=None,
    )
    camera_obj._initial_data = camera_obj.dict()

    await camera_obj.set_lcd_text(DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={
            "lcdMessage": {
                "type": DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR.value,
                "text": DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR.value.replace("_", " "),
                "resetAt": None,
            }
        },
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
@patch("pyunifiprotect.data.devices.utc_now")
async def test_camera_set_lcd_text_none(mock_now, camera_obj: Optional[Camera], now: datetime):
    mock_now.return_value = now

    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.emit_message = Mock()
    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_lcd_screen = True
    camera_obj.lcd_message = LCDMessage(
        type=DoorbellMessageType.DO_NOT_DISTURB,
        text=DoorbellMessageType.DO_NOT_DISTURB.value.replace("_", " "),
        reset_at=None,
    )
    camera_obj._initial_data = camera_obj.dict()

    await camera_obj.set_lcd_text(None)

    expected_dt = now - timedelta(seconds=10)
    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={
            "lcdMessage": {
                "resetAt": to_js_time(expected_dt),
            }
        },
    )

    # old/new is actually the same here since the client
    # generating the message is the one that changed it
    camera_obj.api.emit_message.assert_called_with(
        WSSubscriptionMessage(
            action=WSAction.UPDATE,
            new_update_id=camera_obj.api.bootstrap.last_update_id,
            changed_data={"lcd_message": {"reset_at": expected_dt}},
            old_obj=camera_obj,
            new_obj=camera_obj,
        )
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
@patch("pyunifiprotect.data.devices.utc_now")
async def test_camera_set_lcd_text_default(mock_now, camera_obj: Optional[Camera], now: datetime):
    mock_now.return_value = now

    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_lcd_screen = True
    camera_obj.lcd_message = LCDMessage(
        type=DoorbellMessageType.DO_NOT_DISTURB,
        text=DoorbellMessageType.DO_NOT_DISTURB.value.replace("_", " "),
        reset_at=None,
    )
    camera_obj._initial_data = camera_obj.dict()

    await camera_obj.set_lcd_text(DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR, reset_at=DEFAULT)

    expected_dt = now + camera_obj.api.bootstrap.nvr.doorbell_settings.default_message_reset_timeout
    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={
            "lcdMessage": {
                "type": DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR.value,
                "text": DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR.value.replace("_", " "),
                "resetAt": to_js_time(expected_dt),
            }
        },
    )


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_camera_set_privacy_no_privacy(camera_obj: Optional[Camera]):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_privacy_mask = False
    camera_obj._initial_data = camera_obj.dict()

    with pytest.raises(BadRequest):
        await camera_obj.set_privacy(True)

    assert not camera_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("actual_enabled", [True, False])
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("level", [None, -1, 0, 100, 200])
@pytest.mark.parametrize("mode", [None, RecordingMode.ALWAYS])
@pytest.mark.asyncio
async def test_camera_set_privacy(
    camera_obj: Optional[Camera],
    actual_enabled: bool,
    enabled: bool,
    level: Optional[int],
    mode: Optional[RecordingMode],
):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_privacy_mask = True
    camera_obj.privacy_zones = []
    if actual_enabled:
        camera_obj.add_privacy_zone()
    camera_obj.mic_volume = 10
    camera_obj.recording_settings.mode = RecordingMode.NEVER
    camera_obj._initial_data = camera_obj.dict()

    if level in (-1, 200):
        with pytest.raises(ValidationError):
            await camera_obj.set_privacy(enabled, level, mode)

        assert not camera_obj.api.api_request.called
    else:
        expected = {}

        if level is not None:
            expected.update({"micVolume": level})

        if mode is not None:
            expected.update(
                {
                    "recordingSettings": {
                        "mode": mode.value,
                    }
                }
            )

        if actual_enabled != enabled:
            if enabled:
                expected.update({"privacyZones": [CameraZone.create_privacy_zone(0).unifi_dict()]})
            else:
                expected.update({"privacyZones": []})

        await camera_obj.set_privacy(enabled, level, mode)

        if not expected:
            assert not camera_obj.api.api_request.called
        else:
            camera_obj.api.api_request.assert_called_with(
                f"cameras/{camera_obj.id}",
                method="patch",
                json=expected,
            )

        if enabled:
            assert camera_obj.is_privacy_on
        else:
            assert not camera_obj.is_privacy_on


@pytest.mark.asyncio
async def test_nvr_set_default_reset_timeout(nvr_obj: NVR):
    nvr_obj.api.api_request.reset_mock()

    duration = timedelta(seconds=10)
    await nvr_obj.set_default_reset_timeout(duration)

    nvr_obj.api.api_request.assert_called_with(
        "nvr",
        method="patch",
        json={"doorbellSettings": {"defaultMessageResetTimeout": to_ms(duration)}},
    )


@pytest.mark.parametrize("message", ["Test", "fqthpqBgVMKXp9jXX2VeuGeXYfx2mMjB"])
@pytest.mark.asyncio
async def test_nvr_set_default_doorbell_message(nvr_obj: NVR, message: str):
    nvr_obj.api.api_request.reset_mock()

    if len(message) > 30:
        with pytest.raises(ValidationError):
            await nvr_obj.set_default_doorbell_message(message)

        assert not nvr_obj.api.api_request.called
    else:
        await nvr_obj.set_default_doorbell_message(message)

        nvr_obj.api.api_request.assert_called_with(
            "nvr",
            method="patch",
            json={"doorbellSettings": {"defaultMessageText": message}},
        )


@pytest.mark.parametrize("message", ["Welcome", "Test", "fqthpqBgVMKXp9jXX2VeuGeXYfx2mMjB"])
@pytest.mark.asyncio
async def test_nvr_add_custom_doorbell_message(nvr_obj: NVR, message: str):
    nvr_obj.api.api_request.reset_mock()

    nvr_obj.doorbell_settings.custom_messages = ["Welcome"]
    nvr_obj._initial_data = nvr_obj.dict()

    if message != "Test":
        with pytest.raises(BadRequest):
            await nvr_obj.add_custom_doorbell_message(message)

        assert not nvr_obj.api.api_request.called
    else:
        await nvr_obj.add_custom_doorbell_message(message)

        nvr_obj.api.api_request.assert_called_with(
            "nvr", method="patch", json={"doorbellSettings": {"customMessages": ["Welcome", "Test"]}}
        )

        assert nvr_obj.doorbell_settings.all_messages == [
            DoorbellMessage(
                type=DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR,
                text=DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR.value.replace("_", " "),
            ),
            DoorbellMessage(
                type=DoorbellMessageType.DO_NOT_DISTURB,
                text=DoorbellMessageType.DO_NOT_DISTURB.value.replace("_", " "),
            ),
            DoorbellMessage(
                type=DoorbellMessageType.CUSTOM_MESSAGE,
                text="Welcome",
            ),
            DoorbellMessage(
                type=DoorbellMessageType.CUSTOM_MESSAGE,
                text="Test",
            ),
        ]


@pytest.mark.parametrize("message", ["Welcome", "Test"])
@pytest.mark.asyncio
async def test_nvr_remove_custom_doorbell_message(nvr_obj: NVR, message: str):
    nvr_obj.api.api_request.reset_mock()

    nvr_obj.doorbell_settings.custom_messages = ["Welcome"]
    nvr_obj._initial_data = nvr_obj.dict()

    if message == "Test":
        with pytest.raises(BadRequest):
            await nvr_obj.remove_custom_doorbell_message(message)

        assert not nvr_obj.api.api_request.called
    else:
        await nvr_obj.remove_custom_doorbell_message(message)

        nvr_obj.api.api_request.assert_called_with(
            "nvr", method="patch", json={"doorbellSettings": {"customMessages": []}}
        )

        assert nvr_obj.doorbell_settings.all_messages == [
            DoorbellMessage(
                type=DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR,
                text=DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR.value.replace("_", " "),
            ),
            DoorbellMessage(
                type=DoorbellMessageType.DO_NOT_DISTURB,
                text=DoorbellMessageType.DO_NOT_DISTURB.value.replace("_", " "),
            ),
        ]


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_sensor_set_status_light(sensor_obj: Sensor, status: bool):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.led_settings.is_enabled = not status
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.set_status_light(status)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"ledSettings": {"isEnabled": status}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("mount_type", [MountType.DOOR, MountType.NONE])
@pytest.mark.asyncio
async def test_sensor_set_mount_type(sensor_obj: Sensor, mount_type: MountType):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.mount_type = MountType.LEAK
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.set_mount_type(mount_type)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"mountType": mount_type.value},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_sensor_set_motion_status(sensor_obj: Sensor, status: bool):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.motion_settings.is_enabled = not status
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.set_motion_status(status)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"motionSettings": {"isEnabled": status}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_sensor_set_temperature_status(sensor_obj: Sensor, status: bool):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.temperature_settings.is_enabled = not status
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.set_temperature_status(status)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"temperatureSettings": {"isEnabled": status}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_sensor_set_humidity_status(sensor_obj: Sensor, status: bool):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.humidity_settings.is_enabled = not status
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.set_humidity_status(status)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"humiditySettings": {"isEnabled": status}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_sensor_set_light_status(sensor_obj: Sensor, status: bool):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.light_settings.is_enabled = not status
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.set_light_status(status)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"lightSettings": {"isEnabled": status}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_sensor_set_alarm_status(sensor_obj: Sensor, status: bool):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.alarm_settings.is_enabled = not status
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.set_alarm_status(status)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"alarmSettings": {"isEnabled": status}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("sensitivity", [1, 100, -10])
@pytest.mark.asyncio
async def test_sensor_set_motion_sensitivity(
    sensor_obj: Sensor,
    sensitivity: int,
):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.motion_settings.sensitivity = 50
    sensor_obj._initial_data = sensor_obj.dict()

    if sensitivity == -10:
        with pytest.raises(ValidationError):
            await sensor_obj.set_motion_sensitivity(sensitivity)

            assert not sensor_obj.api.api_request.called
    else:
        await sensor_obj.set_motion_sensitivity(sensitivity)

        sensor_obj.api.api_request.assert_called_with(
            f"sensors/{sensor_obj.id}",
            method="patch",
            json={"motionSettings": {"sensitivity": sensitivity}},
        )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("low", [-1.0, 0.0, 25.0])
@pytest.mark.parametrize("high", [20.0, 45.0, 50.0])
@pytest.mark.asyncio
async def test_sensor_set_temperature_safe_range(sensor_obj: Sensor, low: float, high: float):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.temperature_settings.low_threshold = None
    sensor_obj.temperature_settings.high_threshold = None
    sensor_obj._initial_data = sensor_obj.dict()

    if low == -1.0 or high == 50.0 or low > high:
        with pytest.raises(BadRequest):
            await sensor_obj.set_temperature_safe_range(low, high)

            assert not sensor_obj.api.api_request.called
    else:
        await sensor_obj.set_temperature_safe_range(low, high)

        sensor_obj.api.api_request.assert_called_with(
            f"sensors/{sensor_obj.id}",
            method="patch",
            json={"temperatureSettings": {"lowThreshold": low, "highThreshold": high}},
        )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("low", [0.0, 1.0, 50.0])
@pytest.mark.parametrize("high", [45.0, 99.0, 100.0])
@pytest.mark.asyncio
async def test_sensor_set_humidity_safe_range(sensor_obj: Sensor, low: float, high: float):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.humidity_settings.low_threshold = None
    sensor_obj.humidity_settings.high_threshold = None
    sensor_obj._initial_data = sensor_obj.dict()

    if low == 0.0 or high == 100.0 or low > high:
        with pytest.raises(BadRequest):
            await sensor_obj.set_humidity_safe_range(low, high)

            assert not sensor_obj.api.api_request.called
    else:
        await sensor_obj.set_humidity_safe_range(low, high)

        sensor_obj.api.api_request.assert_called_with(
            f"sensors/{sensor_obj.id}",
            method="patch",
            json={"humiditySettings": {"lowThreshold": low, "highThreshold": high}},
        )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("low", [0.0, 1.0, 500.0])
@pytest.mark.parametrize("high", [400.0, 1000.0, 1001.0])
@pytest.mark.asyncio
async def test_sensor_set_light_safe_range(sensor_obj: Sensor, low: float, high: float):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.light_settings.low_threshold = None
    sensor_obj.light_settings.high_threshold = None
    sensor_obj._initial_data = sensor_obj.dict()

    if low == 0.0 or high == 1001.0 or low > high:
        with pytest.raises(BadRequest):
            await sensor_obj.set_light_safe_range(low, high)

            assert not sensor_obj.api.api_request.called
    else:
        await sensor_obj.set_light_safe_range(low, high)

        sensor_obj.api.api_request.assert_called_with(
            f"sensors/{sensor_obj.id}",
            method="patch",
            json={"lightSettings": {"lowThreshold": low, "highThreshold": high}},
        )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_sensor_remove_temperature_safe_range(sensor_obj: Sensor):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.temperature_settings.low_threshold = 10
    sensor_obj.temperature_settings.high_threshold = 20
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.remove_temperature_safe_range()

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"temperatureSettings": {"lowThreshold": None, "highThreshold": None}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_sensor_remove_humidity_safe_range(sensor_obj: Sensor):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.humidity_settings.low_threshold = 10
    sensor_obj.humidity_settings.high_threshold = 20
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.remove_humidity_safe_range()

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"humiditySettings": {"lowThreshold": None, "highThreshold": None}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_sensor_remove_light_safe_range(sensor_obj: Sensor):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.light_settings.low_threshold = 10
    sensor_obj.light_settings.high_threshold = 20
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.remove_light_safe_range()

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"lightSettings": {"lowThreshold": None, "highThreshold": None}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_sensor_set_paired_camera_none(sensor_obj: Sensor):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.camera_id = "bad_id"
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.set_paired_camera(None)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"camera": None},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS or not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_sensor_set_paired_camera(sensor_obj: Light, camera_obj: Camera):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.camera_id = None
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.set_paired_camera(camera_obj)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"camera": camera_obj.id},
    )
