#  type: ignore
from datetime import datetime
from typing import Optional

from pydantic.error_wrappers import ValidationError
import pytest

from pyunifiprotect.data import (
    Camera,
    DoorbellMessageType,
    IRLEDMode,
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
async def test_save_device_no_changes(any_camera_obj: Camera):
    any_camera_obj.api.api_request.reset_mock()

    await any_camera_obj.save_device()

    assert not any_camera_obj.api.api_request.called


@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_light_set_status_light(light_obj: Light, status: bool):
    light_obj.api.api_request.reset_mock()

    light_obj.light_device_settings.is_indicator_enabled = not status
    light_obj._initial_data = light_obj.dict()  # pylint: disable=protected-access

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
    light_obj._initial_data = light_obj.dict()  # pylint: disable=protected-access

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
    light_obj._initial_data = light_obj.dict()  # pylint: disable=protected-access

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
    viewer_obj._initial_data = viewer_obj.dict()  # pylint: disable=protected-access

    await viewer_obj.set_liveview(liveview_obj)

    viewer_obj.api.api_request.assert_called_with(
        f"viewers/{viewer_obj.id}",
        method="patch",
        json={"liveview": liveview_obj.id},
    )


@pytest.mark.parametrize("mode", [RecordingMode.ALWAYS, RecordingMode.DETECTIONS])
@pytest.mark.asyncio
async def test_camera_set_recording_mode(any_camera_obj: Optional[Camera], mode: RecordingMode):
    camera = any_camera_obj
    if camera is None:
        pytest.skip("No Camera obj found")

    camera.api.api_request.reset_mock()

    camera.recording_settings.mode = RecordingMode.NEVER
    camera._initial_data = camera.dict()  # pylint: disable=protected-access

    await camera.set_recording_mode(mode)

    camera.api.api_request.assert_called_with(
        f"cameras/{camera.id}",
        method="patch",
        json={"recordingSettings": {"mode": mode.value}},
    )


@pytest.mark.parametrize("mode", [IRLEDMode.AUTO, IRLEDMode.ON])
@pytest.mark.asyncio
async def test_camera_set_ir_led_model(camera_with_led_ir_obj: Optional[Camera], mode: IRLEDMode):
    camera = camera_with_led_ir_obj
    if camera is None:
        pytest.skip("No Camera obj found")

    camera.api.api_request.reset_mock()

    camera.isp_settings.ir_led_mode = IRLEDMode.OFF
    camera._initial_data = camera.dict()  # pylint: disable=protected-access

    await camera.set_ir_led_model(mode)

    camera.api.api_request.assert_called_with(
        f"cameras/{camera.id}",
        method="patch",
        json={"ispSettings": {"irLedMode": mode.value}},
    )


@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_camera_set_status_light(camera_with_status_obj: Optional[Camera], status: bool):
    camera = camera_with_status_obj
    if camera is None:
        pytest.skip("No Camera obj found")

    camera.api.api_request.reset_mock()

    camera.led_settings.is_enabled = not status
    camera.led_settings.blink_rate = 10
    camera._initial_data = camera.dict()  # pylint: disable=protected-access

    await camera.set_status_light(status)

    camera.api.api_request.assert_called_with(
        f"cameras/{camera.id}",
        method="patch",
        json={"ledSettings": {"isEnabled": status, "blinkRate": 0}},
    )


@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_camera_set_hdr(camera_with_hdr_obj: Optional[Camera], status: bool):
    camera = camera_with_hdr_obj
    if camera is None:
        pytest.skip("No Camera obj found")

    camera.api.api_request.reset_mock()

    camera.hdr_mode = not status
    camera._initial_data = camera.dict()  # pylint: disable=protected-access

    await camera.set_hdr(status)

    camera.api.api_request.assert_called_with(
        f"cameras/{camera.id}",
        method="patch",
        json={"hdrMode": status},
    )


@pytest.mark.asyncio
async def test_camera_set_video_mode(any_camera_obj: Optional[Camera]):
    camera = any_camera_obj
    if camera is None:
        pytest.skip("No Camera obj found")

    camera.api.api_request.reset_mock()

    camera.video_mode = VideoMode.DEFAULT
    camera._initial_data = camera.dict()  # pylint: disable=protected-access

    await camera.set_video_mode(VideoMode.HIGH_FPS)

    camera.api.api_request.assert_called_with(
        f"cameras/{camera.id}",
        method="patch",
        json={"videoMode": VideoMode.HIGH_FPS.value},
    )


@pytest.mark.parametrize("level", [-1, 0, 100, 200])
@pytest.mark.asyncio
async def test_camera_set_camera_zoom(any_camera_obj: Optional[Camera], level: int):
    camera = any_camera_obj
    if camera is None:
        pytest.skip("No Camera obj found")

    camera.api.api_request.reset_mock()

    camera.isp_settings.zoom_position = 10
    camera._initial_data = camera.dict()  # pylint: disable=protected-access

    if level in (-1, 200):
        with pytest.raises(ValidationError):
            await camera.set_camera_zoom(level)

        assert not camera.api.api_request.called
    else:
        await camera.set_camera_zoom(level)

        camera.api.api_request.assert_called_with(
            f"cameras/{camera.id}",
            method="patch",
            json={"ispSettings": {"zoomPosition": level}},
        )


@pytest.mark.parametrize("level", [-1, 0, 3, 4])
@pytest.mark.asyncio
async def test_camera_set_wdr_level(any_camera_obj: Optional[Camera], level: int):
    camera = any_camera_obj
    if camera is None:
        pytest.skip("No Camera obj found")

    camera.api.api_request.reset_mock()

    camera.isp_settings.wdr = 2
    camera._initial_data = camera.dict()  # pylint: disable=protected-access

    if level in (-1, 4):
        with pytest.raises(ValidationError):
            await camera.set_wdr_level(level)

            assert not camera.api.api_request.called
    else:
        await camera.set_wdr_level(level)

        camera.api.api_request.assert_called_with(
            f"cameras/{camera.id}",
            method="patch",
            json={"ispSettings": {"wdr": level}},
        )


@pytest.mark.parametrize("level", [-1, 0, 100, 200])
@pytest.mark.asyncio
async def test_camera_set_mic_volume(camera_with_mic_obj: Optional[Camera], level: int):
    camera = camera_with_mic_obj
    if camera is None:
        pytest.skip("No Camera obj found")

    camera.api.api_request.reset_mock()

    camera.mic_volume = 10
    camera._initial_data = camera.dict()  # pylint: disable=protected-access

    if level in (-1, 200):
        with pytest.raises(ValidationError):
            await camera.set_mic_volume(level)

        assert not camera.api.api_request.called
    else:
        await camera.set_mic_volume(level)

        camera.api.api_request.assert_called_with(
            f"cameras/{camera.id}",
            method="patch",
            json={"micVolume": level},
        )


@pytest.mark.parametrize("level", [-1, 0, 100, 200])
@pytest.mark.asyncio
async def test_camera_set_speaker_volume(camera_with_speaker_obj: Optional[Camera], level: int):
    camera = camera_with_speaker_obj
    if camera is None:
        pytest.skip("No Camera obj found")

    camera.api.api_request.reset_mock()

    camera.speaker_settings.volume = 10
    camera._initial_data = camera.dict()  # pylint: disable=protected-access

    if level in (-1, 200):
        with pytest.raises(ValidationError):
            await camera.set_speaker_volume(level)

        assert not camera.api.api_request.called
    else:
        await camera.set_speaker_volume(level)

        camera.api.api_request.assert_called_with(
            f"cameras/{camera.id}",
            method="patch",
            json={"speakerSettings": {"volume": level}},
        )


@pytest.mark.asyncio
async def test_camera_set_chime_duration_no_chime(camera_with_no_chime_obj: Optional[Camera]):
    camera = camera_with_no_chime_obj
    if camera is None:
        pytest.skip("No Camera obj found")

    camera.api.api_request.reset_mock()

    with pytest.raises(BadRequest):
        await camera.set_chime_duration(1000)

    assert not camera.api.api_request.called


@pytest.mark.parametrize("duration", [-1, 0, 5000, 10000, 20000])
@pytest.mark.asyncio
async def test_camera_set_chime_duration_duration(camera_with_chime_obj: Optional[Camera], duration: int):
    camera = camera_with_chime_obj
    if camera is None:
        pytest.skip("No Camera obj found")

    camera.api.api_request.reset_mock()

    camera.mic_volume = 10
    camera._initial_data = camera.dict()  # pylint: disable=protected-access

    if duration in (-1, 20000):
        with pytest.raises(ValidationError):
            await camera.set_chime_duration(duration)

        assert not camera.api.api_request.called
    else:
        await camera.set_chime_duration(duration)

        camera.api.api_request.assert_called_with(
            f"cameras/{camera.id}",
            method="patch",
            json={"chimeDuration": duration},
        )


@pytest.mark.asyncio
async def test_camera_set_lcd_text_no_lcd(camera_with_no_lcd_obj: Optional[Camera]):
    camera = camera_with_no_lcd_obj
    if camera is None:
        pytest.skip("No Camera obj found")

    camera.api.api_request.reset_mock()

    with pytest.raises(BadRequest):
        await camera.set_lcd_text(DoorbellMessageType.DO_NOT_DISTURB)

    assert not camera.api.api_request.called


@pytest.mark.asyncio
async def test_camera_set_lcd_text_custom(camera_with_lcd_obj: Optional[Camera]):
    camera = camera_with_lcd_obj

    camera.api.api_request.reset_mock()

    camera.lcd_message.type = DoorbellMessageType.DO_NOT_DISTURB
    camera.lcd_message.text = DoorbellMessageType.DO_NOT_DISTURB.value.replace("_", " ")
    camera.lcd_message.reset_at = None
    camera._initial_data = camera.dict()  # pylint: disable=protected-access

    now = datetime.utcnow()
    await camera.set_lcd_text(DoorbellMessageType.CUSTOM_MESSAGE, "Test", now)

    camera.api.api_request.assert_called_with(
        f"cameras/{camera.id}",
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
async def test_camera_set_lcd_text_invalid_text(camera_with_lcd_obj: Optional[Camera]):
    camera = camera_with_lcd_obj
    if camera is None:
        pytest.skip("No Camera obj found")

    camera.api.api_request.reset_mock()

    with pytest.raises(BadRequest):
        await camera.set_lcd_text(DoorbellMessageType.DO_NOT_DISTURB, "Test")

    assert not camera.api.api_request.called


@pytest.mark.asyncio
async def test_camera_set_lcd_text(camera_with_lcd_obj: Optional[Camera]):
    camera = camera_with_lcd_obj
    if camera is None:
        pytest.skip("No Camera obj found")

    camera.api.api_request.reset_mock()

    camera.lcd_message.type = DoorbellMessageType.DO_NOT_DISTURB
    camera.lcd_message.text = DoorbellMessageType.DO_NOT_DISTURB.value.replace("_", " ")
    camera.lcd_message.reset_at = None
    camera._initial_data = camera.dict()  # pylint: disable=protected-access

    await camera.set_lcd_text(DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR)

    camera.api.api_request.assert_called_with(
        f"cameras/{camera.id}",
        method="patch",
        json={
            "lcdMessage": {
                "type": DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR.value,
                "text": DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR.value.replace("_", " "),
            }
        },
    )


@pytest.mark.parametrize("actual_enabled", [True, False])
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("level", [None, -1, 0, 100, 200])
@pytest.mark.parametrize("mode", [None, RecordingMode.ALWAYS])
@pytest.mark.asyncio
async def test_camera_set_privacy(
    camera_with_privacy_obj: Optional[Camera],
    actual_enabled: bool,
    enabled: bool,
    level: Optional[int],
    mode: Optional[RecordingMode],
):
    camera = camera_with_privacy_obj
    if camera is None:
        pytest.skip("No Camera obj found")

    camera.api.api_request.reset_mock()

    camera.privacy_zones = []
    if actual_enabled:
        camera.add_privacy_zone()
    camera.mic_volume = 10
    camera.recording_settings.mode = RecordingMode.NEVER
    camera._initial_data = camera.dict()  # pylint: disable=protected-access

    if level in (-1, 200):
        with pytest.raises(ValidationError):
            await camera.set_privacy(enabled, level, mode)

        assert not camera.api.api_request.called
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

        await camera.set_privacy(enabled, level, mode)

        if expected == {}:
            assert not camera.api.api_request.called
        else:
            camera.api.api_request.assert_called_with(
                f"cameras/{camera.id}",
                method="patch",
                json=expected,
            )
