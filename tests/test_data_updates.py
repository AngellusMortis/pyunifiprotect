# type: ignore
# pylint: disable=protected-access

from datetime import datetime
from typing import Optional

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
from pyunifiprotect.data.devices import CameraZone
from pyunifiprotect.exceptions import BadRequest
from pyunifiprotect.utils import to_js_time


@pytest.mark.asyncio
async def test_save_device_no_changes(camera_obj: Camera):
    camera_obj.api.api_request.reset_mock()

    await camera_obj.save_device()

    assert not camera_obj.api.api_request.called


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


@pytest.mark.parametrize("level", [0, 1, 3, 6, 7])
@pytest.mark.asyncio
async def test_light_set_led_level(light_obj: Light, level: int):
    light_obj.api.api_request.reset_mock()

    light_obj.light_device_settings.led_level = 2
    light_obj._initial_data = light_obj.dict()

    if level in (0, 7):
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


@pytest.mark.parametrize("status", [True, False])
@pytest.mark.parametrize("level", [None, 0, 1, 3, 6, 7])
@pytest.mark.asyncio
async def test_light_set_light(light_obj: Light, status: bool, level: Optional[int]):
    light_obj.api.api_request.reset_mock()

    light_obj.light_on_settings.is_led_force_on = not status
    if level is not None:
        light_obj.light_device_settings.led_level = 2
    light_obj._initial_data = light_obj.dict()

    if level in (0, 7):
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


@pytest.mark.asyncio
async def test_viewer_set_liveview_invalid(viewer_obj: Viewer, liveview_obj: Liveview):
    viewer_obj.api.api_request.reset_mock()

    liveview = liveview_obj.update_from_dict({"id": "bad_id"})

    with pytest.raises(BadRequest):
        await viewer_obj.set_liveview(liveview)

    assert not viewer_obj.api.api_request.called


@pytest.mark.asyncio
async def test_viewer_set_liveview_valid(viewer_obj: Viewer, liveview_obj: Liveview):
    viewer_obj.api.api_request.reset_mock()

    viewer_obj.liveview_id = "bad_id"
    viewer_obj._initial_data = viewer_obj.dict()

    await viewer_obj.set_liveview(liveview_obj)

    viewer_obj.api.api_request.assert_called_with(
        f"viewers/{viewer_obj.id}",
        method="patch",
        json={"liveview": liveview_obj.id},
    )


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


@pytest.mark.asyncio
async def test_camera_set_video_mode(camera_obj: Optional[Camera]):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.video_mode = VideoMode.DEFAULT
    camera_obj._initial_data = camera_obj.dict()

    await camera_obj.set_video_mode(VideoMode.HIGH_FPS)

    camera_obj.api.api_request.assert_called_with(
        f"cameras/{camera_obj.id}",
        method="patch",
        json={"videoMode": VideoMode.HIGH_FPS.value},
    )


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


@pytest.mark.parametrize("level", [-1, 0, 3, 4])
@pytest.mark.asyncio
async def test_camera_set_wdr_level(camera_obj: Optional[Camera], level: int):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

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


@pytest.mark.parametrize("duration", [-1, 0, 5000, 10000, 20000])
@pytest.mark.asyncio
async def test_camera_set_chime_duration_duration(camera_obj: Optional[Camera], duration: int):
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    camera_obj.api.api_request.reset_mock()

    camera_obj.feature_flags.has_chime = True
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
            }
        },
    )


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

        if expected == {}:
            assert not camera_obj.api.api_request.called
        else:
            camera_obj.api.api_request.assert_called_with(
                f"cameras/{camera_obj.id}",
                method="patch",
                json=expected,
            )
