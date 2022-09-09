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
    RecordingMode,
    VideoMode,
)
from pyunifiprotect.data.devices import CameraZone
from pyunifiprotect.data.types import DEFAULT, SmartDetectObjectType
from pyunifiprotect.data.websocket import WSAction, WSSubscriptionMessage
from pyunifiprotect.exceptions import BadRequest
from pyunifiprotect.utils import to_js_time
from tests.conftest import TEST_CAMERA_EXISTS


@pytest.mark.skipif(not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_camera_set_motion_detection(camera_obj: Optional[Camera], status: bool):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.recording_settings.enable_motion_detection = not status
    camera_obj._initial_data = camera_obj.dict()

    await camera_obj.set_motion_detection(status)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"recordingSettings": {"enableMotionDetection": status}},
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
@pytest.mark.parametrize("duration", [-1, 0, 0.5, 1, 20])
@pytest.mark.asyncio
async def test_camera_set_chime_duration_duration(camera_obj: Optional[Camera], duration: int):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_chime = True
    camera_obj.chime_duration = 300
    camera_obj.mic_volume = 10
    camera_obj._initial_data = camera_obj.dict()

    if duration in (-1, 20):
        with pytest.raises(BadRequest):
            await camera_obj.set_chime_duration(duration)

        assert not camera_obj.api.api_request.called
    else:
        await camera_obj.set_chime_duration(duration)

        camera_obj.api.api_request.assert_called_with(
            f"cameras/{camera_obj.id}",
            method="patch",
            json={"chimeDuration": duration * 1000},
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
