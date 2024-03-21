"""UniFi Protect Data."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime, timedelta
from functools import cache
from ipaddress import IPv4Address
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Optional, Union, cast
import warnings

try:
    from pydantic.v1.fields import PrivateAttr
except ImportError:
    from pydantic.fields import PrivateAttr

from pyunifiprotect.data.base import (
    EVENT_PING_INTERVAL,
    ProtectAdoptableDeviceModel,
    ProtectBaseObject,
    ProtectMotionDeviceModel,
)
from pyunifiprotect.data.types import (
    DEFAULT,
    DEFAULT_TYPE,
    AudioCodecs,
    AudioStyle,
    AutoExposureMode,
    ChimeType,
    Color,
    DoorbellMessageType,
    FocusMode,
    GeofencingSetting,
    HDRMode,
    ICRCustomValue,
    ICRLuxValue,
    ICRSensitivity,
    IRLEDMode,
    IteratorCallback,
    LEDLevel,
    LensType,
    LightModeEnableType,
    LightModeType,
    LockStatusType,
    LowMedHigh,
    ModelType,
    MotionAlgorithm,
    MountPosition,
    MountType,
    Percent,
    PercentInt,
    PermissionNode,
    ProgressCallback,
    RecordingMode,
    RepeatTimes,
    SensorStatusType,
    SmartDetectAudioType,
    SmartDetectObjectType,
    TwoByteInt,
    VideoMode,
    WDRLevel,
)
from pyunifiprotect.data.user import User
from pyunifiprotect.exceptions import BadRequest, NotAuthorized, StreamError
from pyunifiprotect.stream import TalkbackStream
from pyunifiprotect.utils import (
    convert_smart_audio_types,
    convert_smart_types,
    convert_video_modes,
    from_js_time,
    process_datetime,
    serialize_point,
    to_js_time,
    utc_now,
)

if TYPE_CHECKING:
    from pyunifiprotect.data.nvr import Event, Liveview

PRIVACY_ZONE_NAME = "pyufp_privacy_zone"
LUX_MAPPING_VALUES = [
    30,
    25,
    20,
    15,
    12,
    10,
    7,
    5,
    3,
    1,
]

_LOGGER = logging.getLogger(__name__)


class LightDeviceSettings(ProtectBaseObject):
    # Status LED
    is_indicator_enabled: bool
    # Brightness
    led_level: LEDLevel
    lux_sensitivity: LowMedHigh
    pir_duration: timedelta
    pir_sensitivity: PercentInt

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "pirDuration" in data and not isinstance(data["pirDuration"], timedelta):
            data["pirDuration"] = timedelta(milliseconds=data["pirDuration"])

        return super().unifi_dict_to_dict(data)


class LightOnSettings(ProtectBaseObject):
    # Manual toggle in UI
    is_led_force_on: bool


class LightModeSettings(ProtectBaseObject):
    # main "Lighting" settings
    mode: LightModeType
    enable_at: LightModeEnableType


class Light(ProtectMotionDeviceModel):
    is_pir_motion_detected: bool
    is_light_on: bool
    is_locating: bool
    light_device_settings: LightDeviceSettings
    light_on_settings: LightOnSettings
    light_mode_settings: LightModeSettings
    camera_id: Optional[str]
    is_camera_paired: bool

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "camera": "cameraId"}

    @classmethod
    @cache
    def _get_read_only_fields(cls) -> set[str]:
        return super()._get_read_only_fields() | {
            "isPirMotionDetected",
            "isLightOn",
            "isLocating",
        }

    @property
    def camera(self) -> Optional[Camera]:
        """Paired Camera will always be none if no camera is paired"""

        if self.camera_id is None:
            return None

        return self.api.bootstrap.cameras[self.camera_id]

    async def set_paired_camera(self, camera: Optional[Camera]) -> None:
        """Sets the camera paired with the light"""

        async with self._update_lock:
            await asyncio.sleep(
                0,
            )  # yield to the event loop once we have the lock to process any pending updates
            data_before_changes = self.dict_with_excludes()
            if camera is None:
                self.camera_id = None
            else:
                self.camera_id = camera.id
            await self.save_device(data_before_changes, force_emit=True)

    async def set_status_light(self, enabled: bool) -> None:
        """Sets the status indicator light for the light"""

        def callback() -> None:
            self.light_device_settings.is_indicator_enabled = enabled

        await self.queue_update(callback)

    async def set_led_level(self, led_level: int) -> None:
        """Sets the LED level for the light"""

        def callback() -> None:
            self.light_device_settings.led_level = LEDLevel(led_level)

        await self.queue_update(callback)

    async def set_light(self, enabled: bool, led_level: Optional[int] = None) -> None:
        """Force turns on/off the light"""

        def callback() -> None:
            self.light_on_settings.is_led_force_on = enabled
            if led_level is not None:
                self.light_device_settings.led_level = LEDLevel(led_level)

        await self.queue_update(callback)

    async def set_sensitivity(self, sensitivity: int) -> None:
        """Sets motion sensitivity"""

        def callback() -> None:
            self.light_device_settings.pir_sensitivity = PercentInt(sensitivity)

        await self.queue_update(callback)

    async def set_duration(self, duration: timedelta) -> None:
        """Sets motion sensitivity"""

        if duration.total_seconds() < 15 or duration.total_seconds() > 900:
            raise BadRequest("Duration outside of 15s to 900s range")

        def callback() -> None:
            self.light_device_settings.pir_duration = duration

        await self.queue_update(callback)

    async def set_light_settings(
        self,
        mode: LightModeType,
        enable_at: Optional[LightModeEnableType] = None,
        duration: Optional[timedelta] = None,
        sensitivity: Optional[int] = None,
    ) -> None:
        """Updates various Light settings.

        Args:
        ----
            mode: Light trigger mode
            enable_at: Then the light automatically turns on by itself
            duration: How long the light should remain on after motion, must be timedelta between 15s and 900s
            sensitivity: PIR Motion sensitivity
        """

        if duration is not None and (
            duration.total_seconds() < 15 or duration.total_seconds() > 900
        ):
            raise BadRequest("Duration outside of 15s to 900s range")

        def callback() -> None:
            self.light_mode_settings.mode = mode
            if enable_at is not None:
                self.light_mode_settings.enable_at = enable_at
            if duration is not None:
                self.light_device_settings.pir_duration = duration
            if sensitivity is not None:
                self.light_device_settings.pir_sensitivity = PercentInt(sensitivity)

        await self.queue_update(callback)


class CameraChannel(ProtectBaseObject):
    id: int  # read only
    video_id: str  # read only
    name: str  # read only
    enabled: bool  # read only
    is_rtsp_enabled: bool
    rtsp_alias: Optional[str]  # read only
    width: int
    height: int
    fps: int
    bitrate: int
    min_bitrate: int  # read only
    max_bitrate: int  # read only
    min_client_adaptive_bit_rate: Optional[int]  # read only
    min_motion_adaptive_bit_rate: Optional[int]  # read only
    fps_values: list[int]  # read only
    idr_interval: int
    # 3.0.22+
    auto_bitrate: Optional[bool] = None
    auto_fps: Optional[bool] = None

    _rtsp_url: Optional[str] = PrivateAttr(None)
    _rtsps_url: Optional[str] = PrivateAttr(None)

    @property
    def rtsp_url(self) -> Optional[str]:
        if not self.is_rtsp_enabled or self.rtsp_alias is None:
            return None

        if self._rtsp_url is not None:
            return self._rtsp_url
        self._rtsp_url = f"rtsp://{self.api.connection_host}:{self.api.bootstrap.nvr.ports.rtsp}/{self.rtsp_alias}"
        return self._rtsp_url

    @property
    def rtsps_url(self) -> Optional[str]:
        if not self.is_rtsp_enabled or self.rtsp_alias is None:
            return None

        if self._rtsps_url is not None:
            return self._rtsps_url
        self._rtsps_url = f"rtsps://{self.api.connection_host}:{self.api.bootstrap.nvr.ports.rtsps}/{self.rtsp_alias}?enableSrtp"
        return self._rtsps_url

    @property
    def is_package(self) -> bool:
        return self.fps <= 2


class ISPSettings(ProtectBaseObject):
    ae_mode: AutoExposureMode
    ir_led_mode: IRLEDMode
    ir_led_level: TwoByteInt
    wdr: WDRLevel
    icr_sensitivity: ICRSensitivity
    brightness: int
    contrast: int
    hue: int
    saturation: int
    sharpness: int
    denoise: int
    is_flipped_vertical: bool
    is_flipped_horizontal: bool
    is_auto_rotate_enabled: bool
    is_ldc_enabled: bool
    is_3dnr_enabled: bool
    is_external_ir_enabled: bool
    is_aggressive_anti_flicker_enabled: bool
    is_pause_motion_enabled: bool
    d_zoom_center_x: int
    d_zoom_center_y: int
    d_zoom_scale: int
    d_zoom_stream_id: int
    focus_mode: Optional[FocusMode] = None
    focus_position: int
    touch_focus_x: Optional[int]
    touch_focus_y: Optional[int]
    zoom_position: PercentInt
    mount_position: Optional[MountPosition] = None
    # requires 2.8.14+
    is_color_night_vision_enabled: Optional[bool] = None
    # 3.0.22+
    hdr_mode: Optional[HDRMode] = None
    icr_custom_value: Optional[ICRCustomValue] = None
    icr_switch_mode: Optional[str] = None
    spotlight_duration: Optional[int] = None

    def unifi_dict(
        self,
        data: Optional[dict[str, Any]] = None,
        exclude: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "focusMode" in data and data["focusMode"] is None:
            del data["focusMode"]

        return data


class OSDSettings(ProtectBaseObject):
    # Overlay Information
    is_name_enabled: bool
    is_date_enabled: bool
    is_logo_enabled: bool
    is_debug_enabled: bool


class LEDSettings(ProtectBaseObject):
    # Status Light
    is_enabled: bool
    blink_rate: int  # in milliseconds betweeen blinks, 0 = solid


class SpeakerSettings(ProtectBaseObject):
    is_enabled: bool
    # Status Sounds
    are_system_sounds_enabled: bool
    volume: PercentInt


class RecordingSettings(ProtectBaseObject):
    # Seconds to record before Motion
    pre_padding: timedelta
    # Seconds to record after Motion
    post_padding: timedelta
    # Seconds of Motion Needed
    min_motion_event_trigger: timedelta
    end_motion_event_delay: timedelta
    suppress_illumination_surge: bool
    # High Frame Rate Mode
    mode: RecordingMode
    geofencing: GeofencingSetting
    motion_algorithm: MotionAlgorithm
    enable_motion_detection: Optional[bool] = None
    use_new_motion_algorithm: bool
    # requires 2.9.20+
    in_schedule_mode: Optional[str] = None
    out_schedule_mode: Optional[str] = None
    # 2.11.13+
    retention_duration: Optional[datetime] = None
    smart_detect_post_padding: Optional[timedelta] = None
    smart_detect_pre_padding: Optional[timedelta] = None

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "retentionDurationMs": "retentionDuration",
        }

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "prePaddingSecs" in data:
            data["prePadding"] = timedelta(seconds=data.pop("prePaddingSecs"))
        if "postPaddingSecs" in data:
            data["postPadding"] = timedelta(seconds=data.pop("postPaddingSecs"))
        if "smartDetectPrePaddingSecs" in data:
            data["smartDetectPrePadding"] = timedelta(
                seconds=data.pop("smartDetectPrePaddingSecs"),
            )
        if "smartDetectPostPaddingSecs" in data:
            data["smartDetectPostPadding"] = timedelta(
                seconds=data.pop("smartDetectPostPaddingSecs"),
            )
        if "minMotionEventTrigger" in data and not isinstance(
            data["minMotionEventTrigger"],
            timedelta,
        ):
            data["minMotionEventTrigger"] = timedelta(
                seconds=data["minMotionEventTrigger"],
            )
        if "endMotionEventDelay" in data and not isinstance(
            data["endMotionEventDelay"],
            timedelta,
        ):
            data["endMotionEventDelay"] = timedelta(seconds=data["endMotionEventDelay"])

        return super().unifi_dict_to_dict(data)

    def unifi_dict(
        self,
        data: Optional[dict[str, Any]] = None,
        exclude: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "prePadding" in data:
            data["prePaddingSecs"] = data.pop("prePadding") // 1000
        if "postPadding" in data:
            data["postPaddingSecs"] = data.pop("postPadding") // 1000
        if (
            "smartDetectPrePadding" in data
            and data["smartDetectPrePadding"] is not None
        ):
            data["smartDetectPrePaddingSecs"] = (
                data.pop("smartDetectPrePadding") // 1000
            )
        if (
            "smartDetectPostPadding" in data
            and data["smartDetectPostPadding"] is not None
        ):
            data["smartDetectPostPaddingSecs"] = (
                data.pop("smartDetectPostPadding") // 1000
            )
        if "minMotionEventTrigger" in data:
            data["minMotionEventTrigger"] = data.pop("minMotionEventTrigger") // 1000
        if "endMotionEventDelay" in data:
            data["endMotionEventDelay"] = data.pop("endMotionEventDelay") // 1000

        return data


class SmartDetectSettings(ProtectBaseObject):
    object_types: list[SmartDetectObjectType]
    audio_types: Optional[list[SmartDetectAudioType]] = None
    # requires 2.8.22+
    auto_tracking_object_types: Optional[list[SmartDetectObjectType]] = None

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "objectTypes" in data:
            data["objectTypes"] = convert_smart_types(data.pop("objectTypes"))
        if "audioTypes" in data:
            data["audioTypes"] = convert_smart_audio_types(data.pop("audioTypes"))
        if "autoTrackingObjectTypes" in data:
            data["autoTrackingObjectTypes"] = convert_smart_types(
                data.pop("autoTrackingObjectTypes"),
            )

        return super().unifi_dict_to_dict(data)


class LCDMessage(ProtectBaseObject):
    type: DoorbellMessageType
    text: str
    reset_at: Optional[datetime] = None

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "resetAt" in data:
            data["resetAt"] = process_datetime(data, "resetAt")
        if "text" in data:
            # UniFi Protect bug: some times LCD messages can get into a bad state where message = DEFAULT MESSAGE, but no type
            if "type" not in data:
                data["type"] = DoorbellMessageType.CUSTOM_MESSAGE.value

            data["text"] = cls._fix_text(data["text"], data["type"])

        return super().unifi_dict_to_dict(data)

    @classmethod
    def _fix_text(cls, text: str, text_type: Optional[str]) -> str:
        if text_type is None:
            text_type = cls.type.value

        if text_type != DoorbellMessageType.CUSTOM_MESSAGE.value:
            text = text_type.replace("_", " ")

        return text

    def unifi_dict(
        self,
        data: Optional[dict[str, Any]] = None,
        exclude: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "text" in data:
            try:
                msg_type = self.type.value
            except AttributeError:
                msg_type = None

            data["text"] = self._fix_text(data["text"], data.get("type", msg_type))
        if "resetAt" in data:
            data["resetAt"] = to_js_time(data["resetAt"])

        return data


class TalkbackSettings(ProtectBaseObject):
    type_fmt: AudioCodecs
    type_in: str
    bind_addr: IPv4Address
    bind_port: int
    filter_addr: Optional[str]  # can be used to restrict sender address
    filter_port: Optional[int]  # can be used to restrict sender port
    channels: int  # 1 or 2
    sampling_rate: int  # 8000, 11025, 22050, 44100, 48000
    bits_per_sample: int
    quality: PercentInt  # only for vorbis


class WifiStats(ProtectBaseObject):
    channel: Optional[int]
    frequency: Optional[int]
    link_speed_mbps: Optional[str]
    signal_quality: PercentInt
    signal_strength: int


class VideoStats(ProtectBaseObject):
    recording_start: Optional[datetime]
    recording_end: Optional[datetime]
    recording_start_lq: Optional[datetime]
    recording_end_lq: Optional[datetime]
    timelapse_start: Optional[datetime]
    timelapse_end: Optional[datetime]
    timelapse_start_lq: Optional[datetime]
    timelapse_end_lq: Optional[datetime]

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "recordingStartLQ": "recordingStartLq",
            "recordingEndLQ": "recordingEndLq",
            "timelapseStartLQ": "timelapseStartLq",
            "timelapseEndLQ": "timelapseEndLq",
        }

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "recordingStart" in data:
            data["recordingStart"] = process_datetime(data, "recordingStart")
        if "recordingEnd" in data:
            data["recordingEnd"] = process_datetime(data, "recordingEnd")
        if "recordingStartLQ" in data:
            data["recordingStartLQ"] = process_datetime(data, "recordingStartLQ")
        if "recordingEndLQ" in data:
            data["recordingEndLQ"] = process_datetime(data, "recordingEndLQ")
        if "timelapseStart" in data:
            data["timelapseStart"] = process_datetime(data, "timelapseStart")
        if "timelapseEnd" in data:
            data["timelapseEnd"] = process_datetime(data, "timelapseEnd")
        if "timelapseStartLQ" in data:
            data["timelapseStartLQ"] = process_datetime(data, "timelapseStartLQ")
        if "timelapseEndLQ" in data:
            data["timelapseEndLQ"] = process_datetime(data, "timelapseEndLQ")

        return super().unifi_dict_to_dict(data)


class StorageStats(ProtectBaseObject):
    used: Optional[int]  # bytes
    rate: Optional[float]  # bytes / millisecond

    @property
    def rate_per_second(self) -> Optional[float]:
        if self.rate is None:
            return None

        return self.rate * 1000

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "rate" not in data:
            data["rate"] = None

        return super().unifi_dict_to_dict(data)

    def unifi_dict(
        self,
        data: Optional[dict[str, Any]] = None,
        exclude: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "rate" in data and data["rate"] is None:
            del data["rate"]

        return data


class CameraStats(ProtectBaseObject):
    rx_bytes: int
    tx_bytes: int
    wifi: WifiStats
    video: VideoStats
    storage: Optional[StorageStats]
    wifi_quality: PercentInt
    wifi_strength: int

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "storage" in data and data["storage"] == {}:
            del data["storage"]

        return super().unifi_dict_to_dict(data)

    def unifi_dict(
        self,
        data: Optional[dict[str, Any]] = None,
        exclude: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "storage" in data and data["storage"] is None:
            data["storage"] = {}

        return data


class CameraZone(ProtectBaseObject):
    id: int
    name: str
    color: Color
    points: list[tuple[Percent, Percent]]

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        data = super().unifi_dict_to_dict(data)
        if "points" in data and isinstance(data["points"], Iterable):
            data["points"] = [(p[0], p[1]) for p in data["points"]]

        return data

    def unifi_dict(
        self,
        data: Optional[dict[str, Any]] = None,
        exclude: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "points" in data:
            data["points"] = [serialize_point(p) for p in data["points"]]

        return data

    @staticmethod
    def create_privacy_zone(zone_id: int) -> CameraZone:
        return CameraZone(
            id=zone_id,
            name=PRIVACY_ZONE_NAME,
            color=Color("#85BCEC"),
            points=[[0, 0], [1, 0], [1, 1], [0, 1]],  # type: ignore[list-item]
        )


class MotionZone(CameraZone):
    sensitivity: PercentInt


class SmartMotionZone(MotionZone):
    object_types: list[SmartDetectObjectType]

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "objectTypes" in data:
            data["objectTypes"] = convert_smart_types(data.pop("objectTypes"))

        return super().unifi_dict_to_dict(data)


class PrivacyMaskCapability(ProtectBaseObject):
    max_masks: Optional[int]
    rectangle_only: bool


class HotplugExtender(ProtectBaseObject):
    has_flash: Optional[bool] = None
    has_ir: Optional[bool] = None
    has_radar: Optional[bool] = None
    is_attached: Optional[bool] = None
    # 3.0.22+
    flash_range: Optional[Any] = None

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "hasIR": "hasIr"}


class Hotplug(ProtectBaseObject):
    audio: Optional[bool] = None
    video: Optional[bool] = None
    extender: Optional[HotplugExtender] = None
    # 2.8.35+
    standalone_adoption: Optional[bool] = None


class CameraFeatureFlags(ProtectBaseObject):
    can_adjust_ir_led_level: bool
    can_magic_zoom: bool
    can_optical_zoom: bool
    can_touch_focus: bool
    has_accelerometer: bool
    has_aec: bool
    has_bluetooth: bool
    has_chime: bool
    has_external_ir: bool
    has_icr_sensitivity: bool
    has_ldc: bool
    has_led_ir: bool
    has_led_status: bool
    has_line_in: bool
    has_mic: bool
    has_privacy_mask: bool
    has_rtc: bool
    has_sd_card: bool
    has_speaker: bool
    has_wifi: bool
    has_hdr: bool
    has_auto_icr_only: bool
    video_modes: list[VideoMode]
    video_mode_max_fps: list[int]
    has_motion_zones: bool
    has_lcd_screen: bool
    smart_detect_types: list[SmartDetectObjectType]
    motion_algorithms: list[MotionAlgorithm]
    has_square_event_thumbnail: bool
    has_package_camera: bool
    privacy_mask_capability: PrivacyMaskCapability
    has_smart_detect: bool
    audio: list[str] = []
    audio_codecs: list[AudioCodecs] = []
    mount_positions: list[MountPosition] = []
    has_infrared: Optional[bool] = None
    lens_type: Optional[LensType] = None
    hotplug: Optional[Hotplug] = None
    smart_detect_audio_types: Optional[list[SmartDetectAudioType]] = None
    # 2.7.18+
    is_doorbell: bool
    # 2.8.22+
    lens_model: Optional[str] = None
    # 2.9.20+
    has_color_lcd_screen: Optional[bool] = None
    has_line_crossing: Optional[bool] = None
    has_line_crossing_counting: Optional[bool] = None
    has_liveview_tracking: Optional[bool] = None
    # 2.10.10+
    has_flash: Optional[bool] = None
    is_ptz: Optional[bool] = None
    # 2.11.13+
    audio_style: Optional[list[AudioStyle]] = None
    has_vertical_flip: Optional[bool] = None
    # 3.0.22+
    flash_range: Optional[Any] = None

    # TODO:
    # focus
    # pan
    # tilt
    # zoom

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "smartDetectTypes" in data:
            data["smartDetectTypes"] = convert_smart_types(data.pop("smartDetectTypes"))
        if "smartDetectAudioTypes" in data:
            data["smartDetectAudioTypes"] = convert_smart_audio_types(
                data.pop("smartDetectAudioTypes"),
            )
        if "videoModes" in data:
            data["videoModes"] = convert_video_modes(data.pop("videoModes"))

        # backport support for `is_doorbell` to older versions of Protect
        if "hasChime" in data and "isDoorbell" not in data:
            data["isDoorbell"] = data["hasChime"]

        return super().unifi_dict_to_dict(data)

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "hasAutoICROnly": "hasAutoIcrOnly"}

    @property
    def has_highfps(self) -> bool:
        return VideoMode.HIGH_FPS in self.video_modes

    @property
    def has_wdr(self) -> bool:
        return not self.has_hdr


class CameraLenses(ProtectBaseObject):
    id: int
    video: VideoStats


class CameraHomekitSettings(ProtectBaseObject):
    microphone_muted: bool
    speaker_muted: bool
    stream_in_progress: bool
    talkback_settings_active: bool


class CameraAudioSettings(ProtectBaseObject):
    style: list[AudioStyle]


class Camera(ProtectMotionDeviceModel):
    is_deleting: bool
    # Microphone Sensitivity
    mic_volume: PercentInt
    is_mic_enabled: bool
    is_recording: bool
    is_motion_detected: bool
    is_smart_detected: bool
    phy_rate: Optional[float]
    hdr_mode: bool
    # Recording Quality -> High Frame
    video_mode: VideoMode
    is_probing_for_wifi: bool
    chime_duration: timedelta
    last_ring: Optional[datetime]
    is_live_heatmap_enabled: bool
    video_reconfiguration_in_progress: bool
    channels: list[CameraChannel]
    isp_settings: ISPSettings
    talkback_settings: TalkbackSettings
    osd_settings: OSDSettings
    led_settings: LEDSettings
    speaker_settings: SpeakerSettings
    recording_settings: RecordingSettings
    smart_detect_settings: SmartDetectSettings
    motion_zones: list[MotionZone]
    privacy_zones: list[CameraZone]
    smart_detect_zones: list[SmartMotionZone]
    stats: CameraStats
    feature_flags: CameraFeatureFlags
    lcd_message: Optional[LCDMessage]
    lenses: list[CameraLenses]
    platform: str
    has_speaker: bool
    has_wifi: bool
    audio_bitrate: int
    can_manage: bool
    is_managed: bool
    voltage: Optional[float]
    # requires 1.21+
    is_poor_network: Optional[bool]
    is_wireless_uplink_enabled: Optional[bool]
    # requires 2.6.13+
    homekit_settings: Optional[CameraHomekitSettings] = None
    # requires 2.6.17+
    ap_mgmt_ip: Optional[IPv4Address] = None
    # requires 2.7.5+
    is_waterproof_case_attached: Optional[bool] = None
    last_disconnect: Optional[datetime] = None
    # requires 2.8.14+
    is_2k: Optional[bool] = None
    is_4k: Optional[bool] = None
    use_global: Optional[bool] = None
    # requires 2.8.22+
    user_configured_ap: Optional[bool] = None
    # requires 2.9.20+
    has_recordings: Optional[bool] = None
    # requires 2.10.10+
    is_ptz: Optional[bool] = None
    # requires 2.11.13+
    audio_settings: Optional[CameraAudioSettings] = None

    # TODO: used for adopting
    # apMac read only
    # apRssi read only
    # elementInfo read only

    # TODO:
    # lastPrivacyZonePositionId
    # smartDetectLines
    # streamSharing read only
    # stopStreamLevel
    # uplinkDevice
    # recordingSchedulesV2

    # not directly from UniFi
    last_ring_event_id: Optional[str] = None
    last_smart_detect: Optional[datetime] = None
    last_smart_audio_detect: Optional[datetime] = None
    last_smart_detect_event_id: Optional[str] = None
    last_smart_audio_detect_event_id: Optional[str] = None
    last_smart_detects: dict[SmartDetectObjectType, datetime] = {}
    last_smart_audio_detects: dict[SmartDetectAudioType, datetime] = {}
    last_smart_detect_event_ids: dict[SmartDetectObjectType, str] = {}
    last_smart_audio_detect_event_ids: dict[SmartDetectAudioType, str] = {}
    talkback_stream: Optional[TalkbackStream] = None
    _last_ring_timeout: Optional[datetime] = PrivateAttr(None)

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "is2K": "is2k", "is4K": "is4k"}

    @classmethod
    @cache
    def _get_excluded_changed_fields(cls) -> set[str]:
        return super()._get_excluded_changed_fields() | {
            "last_ring_event_id",
            "last_smart_detect",
            "last_smart_audio_detect",
            "last_smart_detect_event_id",
            "last_smart_audio_detect_event_id",
            "last_smart_detects",
            "last_smart_audio_detects",
            "last_smart_detect_event_ids",
            "last_smart_audio_detect_event_ids",
            "talkback_stream",
        }

    @classmethod
    @cache
    def _get_read_only_fields(cls) -> set[str]:
        return super()._get_read_only_fields() | {
            "stats",
            "isDeleting",
            "isRecording",
            "isMotionDetected",
            "isSmartDetected",
            "phyRate",
            "isProbingForWifi",
            "lastRing",
            "isLiveHeatmapEnabled",
            "videoReconfigurationInProgress",
            "lenses",
            "isPoorNetwork",
            "featureFlags",
        }

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        # LCD messages comes back as empty dict {}
        if "lcdMessage" in data and len(data["lcdMessage"].keys()) == 0:
            del data["lcdMessage"]
        if "chimeDuration" in data and not isinstance(data["chimeDuration"], timedelta):
            data["chimeDuration"] = timedelta(milliseconds=data["chimeDuration"])

        return super().unifi_dict_to_dict(data)

    def unifi_dict(
        self,
        data: Optional[dict[str, Any]] = None,
        exclude: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        if data is not None:
            if "motion_zones" in data:
                data["motion_zones"] = [
                    MotionZone(**z).unifi_dict() for z in data["motion_zones"]
                ]
            if "privacy_zones" in data:
                data["privacy_zones"] = [
                    CameraZone(**z).unifi_dict() for z in data["privacy_zones"]
                ]
            if "smart_detect_zones" in data:
                data["smart_detect_zones"] = [
                    SmartMotionZone(**z).unifi_dict()
                    for z in data["smart_detect_zones"]
                ]

        data = super().unifi_dict(data=data, exclude=exclude)

        if "lastRingEventId" in data:
            del data["lastRingEventId"]
        if "lastSmartDetect" in data:
            del data["lastSmartDetect"]
        if "lastSmartAudioDetect" in data:
            del data["lastSmartAudioDetect"]
        if "lastSmartDetectEventId" in data:
            del data["lastSmartDetectEventId"]
        if "lastSmartAudioDetectEventId" in data:
            del data["lastSmartAudioDetectEventId"]
        if "lastSmartDetects" in data:
            del data["lastSmartDetects"]
        if "lastSmartAudioDetects" in data:
            del data["lastSmartAudioDetects"]
        if "lastSmartDetectEventIds" in data:
            del data["lastSmartDetectEventIds"]
        if "lastSmartAudioDetectEventIds" in data:
            del data["lastSmartAudioDetectEventIds"]
        if "talkbackStream" in data:
            del data["talkbackStream"]
        if "lcdMessage" in data and data["lcdMessage"] is None:
            data["lcdMessage"] = {}

        return data

    def get_changed(self, data_before_changes: dict[str, Any]) -> dict[str, Any]:
        updated = super().get_changed(data_before_changes)

        if "lcd_message" in updated:
            lcd_message = updated["lcd_message"]
            # to "clear" LCD message, set reset_at to a time in the past
            if lcd_message is None:
                updated["lcd_message"] = {"reset_at": utc_now() - timedelta(seconds=10)}
            # otherwise, pass full LCD message to prevent issues
            elif self.lcd_message is not None:
                updated["lcd_message"] = self.lcd_message.dict()

            # if reset_at is not passed in, it will default to reset in 1 minute
            if lcd_message is not None and "reset_at" not in lcd_message:
                if self.lcd_message is None:
                    updated["lcd_message"]["reset_at"] = None
                else:
                    updated["lcd_message"]["reset_at"] = self.lcd_message.reset_at

        return updated

    def update_from_dict(self, data: dict[str, Any]) -> Camera:
        # a message in the past is actually a singal to wipe the message
        reset_at = data.get("lcd_message", {}).get("reset_at")
        if reset_at is not None:
            reset_at = from_js_time(reset_at)
            if utc_now() > reset_at:
                data["lcd_message"] = None

        return super().update_from_dict(data)

    @property
    def last_ring_event(self) -> Optional[Event]:
        if self.last_ring_event_id is None:
            return None

        return self.api.bootstrap.events.get(self.last_ring_event_id)

    @property
    def last_smart_detect_event(self) -> Optional[Event]:
        """Get the last smart detect event id."""

        if self.last_smart_detect_event_id is None:
            return None

        return self.api.bootstrap.events.get(self.last_smart_detect_event_id)

    @property
    def hdr_mode_display(self) -> Literal["auto", "off", "always"]:
        """Get HDR mode similar to how Protect interface works."""

        if not self.hdr_mode:
            return "off"
        if self.isp_settings.hdr_mode == HDRMode.NORMAL:
            return "auto"
        return "always"

    @property
    def icr_lux_display(self) -> int | None:
        """Get ICR Custom Lux value similar to how the Protect interface works."""

        if self.isp_settings.icr_custom_value is None:
            return None

        return LUX_MAPPING_VALUES[10 - self.isp_settings.icr_custom_value]

    def get_last_smart_detect_event(
        self,
        smart_type: SmartDetectObjectType,
    ) -> Optional[Event]:
        """Get the last smart detect event for given type."""

        event_id = self.last_smart_detect_event_ids.get(smart_type)
        if event_id is None:
            return None

        return self.api.bootstrap.events.get(event_id)

    @property
    def last_smart_audio_detect_event(self) -> Optional[Event]:
        """Get the last smart audio detect event id."""

        if self.last_smart_audio_detect_event_id is None:
            return None

        return self.api.bootstrap.events.get(self.last_smart_audio_detect_event_id)

    def get_last_smart_audio_detect_event(
        self,
        smart_type: SmartDetectAudioType,
    ) -> Optional[Event]:
        """Get the last smart audio detect event for given type."""

        event_id = self.last_smart_audio_detect_event_ids.get(smart_type)
        if event_id is None:
            return None

        return self.api.bootstrap.events.get(event_id)

    @property
    def timelapse_url(self) -> str:
        return f"{self.api.base_url}/protect/timelapse/{self.id}"

    @property
    def is_privacy_on(self) -> bool:
        index, _ = self.get_privacy_zone()
        return index is not None

    @property
    def is_recording_enabled(self) -> bool:
        """Is recording footage/events from the camera enabled?

        If recording is not enabled, cameras will not produce any footage, thumbnails,
        motion/smart detection events.
        """

        return self.recording_settings.mode != RecordingMode.NEVER

    @property
    def is_motion_detection_on(self) -> bool:
        """Is Motion Detection available and enabled (camera will produce motion events)?"""

        return (
            self.is_recording_enabled
            and self.recording_settings.enable_motion_detection is not False
        )

    @property
    def is_motion_currently_detected(self) -> bool:
        """Is motion currently being detected"""

        return (
            self.is_motion_detection_on
            and self.is_motion_detected
            and self.last_motion_event is not None
            and self.last_motion_event.end is None
        )

    async def set_motion_detection(self, enabled: bool) -> None:
        """Sets motion detection on camera"""

        def callback() -> None:
            self.recording_settings.enable_motion_detection = enabled

        await self.queue_update(callback)

    # object smart detections

    def _is_smart_enabled(self, smart_type: SmartDetectObjectType) -> bool:
        return (
            self.is_recording_enabled
            and smart_type in self.smart_detect_settings.object_types
        )

    def _is_smart_detected(self, smart_type: SmartDetectObjectType) -> bool:
        event = self.get_last_smart_detect_event(smart_type)
        return (
            self._is_smart_enabled(smart_type)
            and self.is_smart_detected
            and event is not None
            and event.end is None
            and smart_type in event.smart_detect_types
        )

    @property
    def is_smart_currently_detected(self) -> bool:
        """Is smart detection currently being detected"""

        return (
            self.is_recording_enabled
            and bool(self.smart_detect_settings.object_types)
            and self.is_smart_detected
            and self.last_smart_detect_event is not None
            and self.last_smart_detect_event.end is None
        )

    # person

    @property
    def can_detect_person(self) -> bool:
        return SmartDetectObjectType.PERSON in self.feature_flags.smart_detect_types

    @property
    def is_person_detection_on(self) -> bool:
        """Is Person Detection available and enabled (camera will produce person smart
        detection events)?
        """

        return self._is_smart_enabled(SmartDetectObjectType.PERSON)

    @property
    def last_person_detect_event(self) -> Optional[Event]:
        """Get the last person smart detection event."""

        return self.get_last_smart_detect_event(SmartDetectObjectType.PERSON)

    @property
    def last_person_detect(self) -> Optional[datetime]:
        """Get the last person smart detection event."""

        return self.last_smart_detects.get(SmartDetectObjectType.PERSON)

    @property
    def is_person_currently_detected(self) -> bool:
        """Is person currently being detected"""

        return self._is_smart_detected(SmartDetectObjectType.PERSON)

    async def set_person_detection(self, enabled: bool) -> None:
        """Toggles person smart detection. Requires camera to have smart detection"""

        return await self._set_object_detect(SmartDetectObjectType.PERSON, enabled)

    @property
    def is_person_tracking_enabled(self) -> bool:
        """Is person tracking enabled"""
        return (
            self.smart_detect_settings.auto_tracking_object_types is not None
            and SmartDetectObjectType.PERSON
            in self.smart_detect_settings.auto_tracking_object_types
        )

    # vehicle

    @property
    def can_detect_vehicle(self) -> bool:
        return SmartDetectObjectType.VEHICLE in self.feature_flags.smart_detect_types

    @property
    def is_vehicle_detection_on(self) -> bool:
        """Is Vehicle Detection available and enabled (camera will produce vehicle smart
        detection events)?
        """

        return self._is_smart_enabled(SmartDetectObjectType.VEHICLE)

    @property
    def last_vehicle_detect_event(self) -> Optional[Event]:
        """Get the last vehicle smart detection event."""

        return self.get_last_smart_detect_event(SmartDetectObjectType.VEHICLE)

    @property
    def last_vehicle_detect(self) -> Optional[datetime]:
        """Get the last vehicle smart detection event."""

        return self.last_smart_detects.get(SmartDetectObjectType.VEHICLE)

    @property
    def is_vehicle_currently_detected(self) -> bool:
        """Is vehicle currently being detected"""

        return self._is_smart_detected(SmartDetectObjectType.VEHICLE)

    async def set_vehicle_detection(self, enabled: bool) -> None:
        """Toggles vehicle smart detection. Requires camera to have smart detection"""

        return await self._set_object_detect(SmartDetectObjectType.VEHICLE, enabled)

    # license plate

    @property
    def can_detect_license_plate(self) -> bool:
        return (
            SmartDetectObjectType.LICENSE_PLATE in self.feature_flags.smart_detect_types
        )

    @property
    def is_license_plate_detection_on(self) -> bool:
        """Is License Plate Detection available and enabled (camera will produce face license
        plate detection events)?
        """

        return self._is_smart_enabled(SmartDetectObjectType.LICENSE_PLATE)

    @property
    def last_license_plate_detect_event(self) -> Optional[Event]:
        """Get the last license plate smart detection event."""

        return self.get_last_smart_detect_event(SmartDetectObjectType.LICENSE_PLATE)

    @property
    def last_license_plate_detect(self) -> Optional[datetime]:
        """Get the last license plate smart detection event."""

        return self.last_smart_detects.get(SmartDetectObjectType.LICENSE_PLATE)

    @property
    def is_license_plate_currently_detected(self) -> bool:
        """Is license plate currently being detected"""

        return self._is_smart_detected(SmartDetectObjectType.LICENSE_PLATE)

    async def set_license_plate_detection(self, enabled: bool) -> None:
        """Toggles license plate smart detection. Requires camera to have smart detection"""

        return await self._set_object_detect(
            SmartDetectObjectType.LICENSE_PLATE,
            enabled,
        )

    # package

    @property
    def can_detect_package(self) -> bool:
        return SmartDetectObjectType.PACKAGE in self.feature_flags.smart_detect_types

    @property
    def is_package_detection_on(self) -> bool:
        """Is Package Detection available and enabled (camera will produce package smart
        detection events)?
        """

        return self._is_smart_enabled(SmartDetectObjectType.PACKAGE)

    @property
    def last_package_detect_event(self) -> Optional[Event]:
        """Get the last package smart detection event."""

        return self.get_last_smart_detect_event(SmartDetectObjectType.PACKAGE)

    @property
    def last_package_detect(self) -> Optional[datetime]:
        """Get the last package smart detection event."""

        return self.last_smart_detects.get(SmartDetectObjectType.PACKAGE)

    @property
    def is_package_currently_detected(self) -> bool:
        """Is package currently being detected"""

        return self._is_smart_detected(SmartDetectObjectType.PACKAGE)

    async def set_package_detection(self, enabled: bool) -> None:
        """Toggles package smart detection. Requires camera to have smart detection"""

        return await self._set_object_detect(SmartDetectObjectType.PACKAGE, enabled)

    # animal

    @property
    def can_detect_animal(self) -> bool:
        return SmartDetectObjectType.ANIMAL in self.feature_flags.smart_detect_types

    @property
    def is_animal_detection_on(self) -> bool:
        """Is Animal Detection available and enabled (camera will produce package smart
        detection events)?
        """

        return self._is_smart_enabled(SmartDetectObjectType.ANIMAL)

    @property
    def last_animal_detect_event(self) -> Optional[Event]:
        """Get the last animal smart detection event."""

        return self.get_last_smart_detect_event(SmartDetectObjectType.ANIMAL)

    @property
    def last_animal_detect(self) -> Optional[datetime]:
        """Get the last animal smart detection event."""

        return self.last_smart_detects.get(SmartDetectObjectType.ANIMAL)

    @property
    def is_animal_currently_detected(self) -> bool:
        """Is animal currently being detected"""

        return self._is_smart_detected(SmartDetectObjectType.ANIMAL)

    async def set_animal_detection(self, enabled: bool) -> None:
        """Toggles animal smart detection. Requires camera to have smart detection"""

        return await self._set_object_detect(SmartDetectObjectType.ANIMAL, enabled)

    # audio smart detections

    def _can_detect_audio(self, smart_type: SmartDetectObjectType) -> bool:
        audio_type = smart_type.audio_type
        return (
            audio_type is not None
            and self.feature_flags.smart_detect_audio_types is not None
            and audio_type in self.feature_flags.smart_detect_audio_types
        )

    def _is_audio_enabled(self, smart_type: SmartDetectObjectType) -> bool:
        audio_type = smart_type.audio_type
        return (
            audio_type is not None
            and self.is_recording_enabled
            and self.feature_flags.smart_detect_audio_types is not None
            and self.smart_detect_settings.audio_types is not None
            and audio_type in self.smart_detect_settings.audio_types
        )

    def _is_audio_detected(self, smart_type: SmartDetectObjectType) -> bool:
        audio_type = smart_type.audio_type
        if audio_type is None:
            return False

        event = self.get_last_smart_audio_detect_event(audio_type)
        return (
            self._is_audio_enabled(smart_type)
            and event is not None
            and event.end is None
            and smart_type in event.smart_detect_types
        )

    @property
    def is_audio_currently_detected(self) -> bool:
        """Is audio detection currently being detected"""

        return (
            self.is_recording_enabled
            and bool(self.smart_detect_settings.audio_types)
            and self.last_smart_audio_detect_event is not None
            and self.last_smart_audio_detect_event.end is None
        )

    # smoke alarm

    @property
    def can_detect_smoke(self) -> bool:
        return self._can_detect_audio(SmartDetectObjectType.SMOKE)

    @property
    def is_smoke_detection_on(self) -> bool:
        """Is Smoke Alarm Detection available and enabled (camera will produce smoke
        smart detection events)?
        """

        return self._is_audio_enabled(SmartDetectObjectType.SMOKE)

    @property
    def last_smoke_detect_event(self) -> Optional[Event]:
        """Get the last person smart detection event."""

        return self.get_last_smart_audio_detect_event(SmartDetectAudioType.SMOKE)

    @property
    def last_smoke_detect(self) -> Optional[datetime]:
        """Get the last smoke smart detection event."""

        return self.last_smart_audio_detects.get(SmartDetectAudioType.SMOKE)

    @property
    def is_smoke_currently_detected(self) -> bool:
        """Is smoke alarm currently being detected"""

        return self._is_audio_detected(SmartDetectObjectType.SMOKE)

    async def set_smoke_detection(self, enabled: bool) -> None:
        """Toggles smoke smart detection. Requires camera to have smart detection"""

        return await self._set_audio_detect(SmartDetectAudioType.SMOKE, enabled)

    # co alarm

    @property
    def can_detect_co(self) -> bool:
        return self._can_detect_audio(SmartDetectObjectType.CMONX)

    @property
    def is_co_detection_on(self) -> bool:
        """Is CO Alarm Detection available and enabled (camera will produce smoke smart
        detection events)?
        """

        return self._is_audio_enabled(SmartDetectObjectType.CMONX)

    @property
    def last_cmonx_detect_event(self) -> Optional[Event]:
        """Get the last CO alarm smart detection event."""

        return self.get_last_smart_audio_detect_event(SmartDetectAudioType.CMONX)

    @property
    def last_cmonx_detect(self) -> Optional[datetime]:
        """Get the last CO alarm smart detection event."""

        return self.last_smart_audio_detects.get(SmartDetectAudioType.CMONX)

    @property
    def is_cmonx_currently_detected(self) -> bool:
        """Is CO alarm currently being detected"""

        return self._is_audio_detected(SmartDetectObjectType.CMONX)

    async def set_cmonx_detection(self, enabled: bool) -> None:
        """Toggles smoke smart detection. Requires camera to have smart detection"""

        return await self._set_audio_detect(SmartDetectAudioType.CMONX, enabled)

    # siren

    @property
    def can_detect_siren(self) -> bool:
        return self._can_detect_audio(SmartDetectObjectType.SIREN)

    @property
    def is_siren_detection_on(self) -> bool:
        """Is Siren Detection available and enabled (camera will produce siren smart
        detection events)?
        """

        return self._is_audio_enabled(SmartDetectObjectType.SIREN)

    @property
    def last_siren_detect_event(self) -> Optional[Event]:
        """Get the last Siren smart detection event."""

        return self.get_last_smart_audio_detect_event(SmartDetectAudioType.SIREN)

    @property
    def last_siren_detect(self) -> Optional[datetime]:
        """Get the last Siren smart detection event."""

        return self.last_smart_audio_detects.get(SmartDetectAudioType.SIREN)

    @property
    def is_siren_currently_detected(self) -> bool:
        """Is Siren currently being detected"""

        return self._is_audio_detected(SmartDetectObjectType.SIREN)

    async def set_siren_detection(self, enabled: bool) -> None:
        """Toggles siren smart detection. Requires camera to have smart detection"""

        return await self._set_audio_detect(SmartDetectAudioType.SIREN, enabled)

    # baby cry

    @property
    def can_detect_baby_cry(self) -> bool:
        return self._can_detect_audio(SmartDetectObjectType.BABY_CRY)

    @property
    def is_baby_cry_detection_on(self) -> bool:
        """Is Baby Cry Detection available and enabled (camera will produce baby cry smart
        detection events)?
        """

        return self._is_audio_enabled(SmartDetectObjectType.BABY_CRY)

    @property
    def last_baby_cry_detect_event(self) -> Optional[Event]:
        """Get the last Baby Cry smart detection event."""

        return self.get_last_smart_audio_detect_event(SmartDetectAudioType.BABY_CRY)

    @property
    def last_baby_cry_detect(self) -> Optional[datetime]:
        """Get the last Baby Cry smart detection event."""

        return self.last_smart_audio_detects.get(SmartDetectAudioType.BABY_CRY)

    @property
    def is_baby_cry_currently_detected(self) -> bool:
        """Is Baby Cry currently being detected"""

        return self._is_audio_detected(SmartDetectObjectType.BABY_CRY)

    async def set_baby_cry_detection(self, enabled: bool) -> None:
        """Toggles baby_cry smart detection. Requires camera to have smart detection"""

        return await self._set_audio_detect(SmartDetectAudioType.BABY_CRY, enabled)

    # speaking

    @property
    def can_detect_speaking(self) -> bool:
        return self._can_detect_audio(SmartDetectObjectType.SPEAK)

    @property
    def is_speaking_detection_on(self) -> bool:
        """Is Speaking Detection available and enabled (camera will produce speaking smart
        detection events)?
        """

        return self._is_audio_enabled(SmartDetectObjectType.SPEAK)

    @property
    def last_speaking_detect_event(self) -> Optional[Event]:
        """Get the last Speaking smart detection event."""

        return self.get_last_smart_audio_detect_event(SmartDetectAudioType.SPEAK)

    @property
    def last_speaking_detect(self) -> Optional[datetime]:
        """Get the last Speaking smart detection event."""

        return self.last_smart_audio_detects.get(SmartDetectAudioType.SPEAK)

    @property
    def is_speaking_currently_detected(self) -> bool:
        """Is Speaking currently being detected"""

        return self._is_audio_detected(SmartDetectObjectType.SPEAK)

    async def set_speaking_detection(self, enabled: bool) -> None:
        """Toggles speaking smart detection. Requires camera to have smart detection"""

        return await self._set_audio_detect(SmartDetectAudioType.SPEAK, enabled)

    # bark

    @property
    def can_detect_bark(self) -> bool:
        return self._can_detect_audio(SmartDetectObjectType.BARK)

    @property
    def is_bark_detection_on(self) -> bool:
        """Is Bark Detection available and enabled (camera will produce barking smart
        detection events)?
        """

        return self._is_audio_enabled(SmartDetectObjectType.BARK)

    @property
    def last_bark_detect_event(self) -> Optional[Event]:
        """Get the last Bark smart detection event."""

        return self.get_last_smart_audio_detect_event(SmartDetectAudioType.BARK)

    @property
    def last_bark_detect(self) -> Optional[datetime]:
        """Get the last Bark smart detection event."""

        return self.last_smart_audio_detects.get(SmartDetectAudioType.BARK)

    @property
    def is_bark_currently_detected(self) -> bool:
        """Is Bark currently being detected"""

        return self._is_audio_detected(SmartDetectObjectType.BARK)

    async def set_bark_detection(self, enabled: bool) -> None:
        """Toggles bark smart detection. Requires camera to have smart detection"""

        return await self._set_audio_detect(SmartDetectAudioType.BARK, enabled)

    # car alarm (burglar in code, car alarm in Protect UI)

    @property
    def can_detect_car_alarm(self) -> bool:
        return self._can_detect_audio(SmartDetectObjectType.BURGLAR)

    @property
    def is_car_alarm_detection_on(self) -> bool:
        """Is Car Alarm Detection available and enabled (camera will produce car alarm smart
        detection events)?
        """

        return self._is_audio_enabled(SmartDetectObjectType.BURGLAR)

    @property
    def last_car_alarm_detect_event(self) -> Optional[Event]:
        """Get the last Car Alarm smart detection event."""

        return self.get_last_smart_audio_detect_event(SmartDetectAudioType.BURGLAR)

    @property
    def last_car_alarm_detect(self) -> Optional[datetime]:
        """Get the last Car Alarm smart detection event."""

        return self.last_smart_audio_detects.get(SmartDetectAudioType.BURGLAR)

    @property
    def is_car_alarm_currently_detected(self) -> bool:
        """Is Car Alarm currently being detected"""

        return self._is_audio_detected(SmartDetectObjectType.BURGLAR)

    async def set_car_alarm_detection(self, enabled: bool) -> None:
        """Toggles car_alarm smart detection. Requires camera to have smart detection"""

        return await self._set_audio_detect(SmartDetectAudioType.BURGLAR, enabled)

    # car horn

    @property
    def can_detect_car_horn(self) -> bool:
        return self._can_detect_audio(SmartDetectObjectType.CAR_HORN)

    @property
    def is_car_horn_detection_on(self) -> bool:
        """Is Car Horn Detection available and enabled (camera will produce car horn smart
        detection events)?
        """

        return self._is_audio_enabled(SmartDetectObjectType.CAR_HORN)

    @property
    def last_car_horn_detect_event(self) -> Optional[Event]:
        """Get the last Car Horn smart detection event."""

        return self.get_last_smart_audio_detect_event(SmartDetectAudioType.CAR_HORN)

    @property
    def last_car_horn_detect(self) -> Optional[datetime]:
        """Get the last Car Horn smart detection event."""

        return self.last_smart_audio_detects.get(SmartDetectAudioType.CAR_HORN)

    @property
    def is_car_horn_currently_detected(self) -> bool:
        """Is Car Horn currently being detected"""

        return self._is_audio_detected(SmartDetectObjectType.CAR_HORN)

    async def set_car_horn_detection(self, enabled: bool) -> None:
        """Toggles car_horn smart detection. Requires camera to have smart detection"""

        return await self._set_audio_detect(SmartDetectAudioType.CAR_HORN, enabled)

    # glass break

    @property
    def can_detect_glass_break(self) -> bool:
        return self._can_detect_audio(SmartDetectObjectType.GLASS_BREAK)

    @property
    def is_glass_break_detection_on(self) -> bool:
        """Is Glass Break available and enabled (camera will produce glass break smart
        detection events)?
        """

        return self._is_audio_enabled(SmartDetectObjectType.GLASS_BREAK)

    @property
    def last_glass_break_detect_event(self) -> Optional[Event]:
        """Get the last Glass Break smart detection event."""

        return self.get_last_smart_audio_detect_event(SmartDetectAudioType.GLASS_BREAK)

    @property
    def last_glass_break_detect(self) -> Optional[datetime]:
        """Get the last Glass Break smart detection event."""

        return self.last_smart_audio_detects.get(SmartDetectAudioType.GLASS_BREAK)

    @property
    def is_glass_break_currently_detected(self) -> bool:
        """Is Glass Break currently being detected"""

        return self._is_audio_detected(SmartDetectObjectType.GLASS_BREAK)

    async def set_glass_break_detection(self, enabled: bool) -> None:
        """Toggles glass_break smart detection. Requires camera to have smart detection"""

        return await self._set_audio_detect(SmartDetectAudioType.GLASS_BREAK, enabled)

    @property
    def is_ringing(self) -> bool:
        if self._last_ring_timeout is None:
            return False
        return utc_now() < self._last_ring_timeout

    @property
    def chime_type(self) -> ChimeType:
        if self.chime_duration.total_seconds() == 0.3:
            return ChimeType.MECHANICAL
        if self.chime_duration.total_seconds() > 0.3:
            return ChimeType.DIGITAL
        return ChimeType.NONE

    @property
    def is_digital_chime(self) -> bool:
        return self.chime_type is ChimeType.DIGITAL

    @property
    def high_camera_channel(self) -> Optional[CameraChannel]:
        if len(self.channels) >= 3:
            return self.channels[0]
        return None

    @property
    def medium_camera_channel(self) -> Optional[CameraChannel]:
        if len(self.channels) >= 3:
            return self.channels[1]
        return None

    @property
    def low_camera_channel(self) -> Optional[CameraChannel]:
        if len(self.channels) >= 3:
            return self.channels[2]
        return None

    @property
    def default_camera_channel(self) -> Optional[CameraChannel]:
        for channel in [
            self.high_camera_channel,
            self.medium_camera_channel,
            self.low_camera_channel,
        ]:
            if channel is not None and channel.is_rtsp_enabled:
                return channel
        return self.high_camera_channel

    @property
    def package_camera_channel(self) -> Optional[CameraChannel]:
        if self.feature_flags.has_package_camera and len(self.channels) == 4:
            return self.channels[3]
        return None

    @property
    def is_high_fps_enabled(self) -> bool:
        return self.video_mode == VideoMode.HIGH_FPS

    @property
    def is_video_ready(self) -> bool:
        return (
            self.feature_flags.lens_type is None
            or self.feature_flags.lens_type != LensType.NONE
        )

    @property
    def has_removable_lens(self) -> bool:
        return (
            self.feature_flags.hotplug is not None
            and self.feature_flags.hotplug.video is not None
        )

    @property
    def has_removable_speaker(self) -> bool:
        return (
            self.feature_flags.hotplug is not None
            and self.feature_flags.hotplug.audio is not None
        )

    @property
    def has_mic(self) -> bool:
        return self.feature_flags.has_mic or self.has_removable_speaker

    @property
    def has_color_night_vision(self) -> bool:
        if (
            self.feature_flags.hotplug is not None
            and self.feature_flags.hotplug.extender is not None
            and self.feature_flags.hotplug.extender.is_attached is not None
        ):
            return self.feature_flags.hotplug.extender.is_attached

        return False

    def set_ring_timeout(self) -> None:
        self._last_ring_timeout = utc_now() + EVENT_PING_INTERVAL
        self._event_callback_ping()

    def get_privacy_zone(self) -> tuple[Optional[int], Optional[CameraZone]]:
        for index, zone in enumerate(self.privacy_zones):
            if zone.name == PRIVACY_ZONE_NAME:
                return index, zone
        return None, None

    def add_privacy_zone(self) -> None:
        index, _ = self.get_privacy_zone()
        if index is None:
            zone_id = 0
            if len(self.privacy_zones) > 0:
                zone_id = self.privacy_zones[-1].id + 1

            self.privacy_zones.append(CameraZone.create_privacy_zone(zone_id))

    def remove_privacy_zone(self) -> None:
        index, _ = self.get_privacy_zone()

        if index is not None:
            self.privacy_zones.pop(index)

    async def get_snapshot(
        self,
        width: Optional[int] = None,
        height: Optional[int] = None,
        dt: Optional[datetime] = None,
    ) -> Optional[bytes]:
        """Gets snapshot for camera.

        Datetime of screenshot is approximate. It may be +/- a few seconds.
        """

        if not self.api.bootstrap.auth_user.can(
            ModelType.CAMERA,
            PermissionNode.READ_MEDIA,
            self,
        ):
            raise NotAuthorized(
                f"Do not have permission to read media for camera: {self.id}",
            )

        if height is None and width is None and self.high_camera_channel is not None:
            height = self.high_camera_channel.height

        return await self.api.get_camera_snapshot(self.id, width, height, dt=dt)

    async def get_package_snapshot(
        self,
        width: Optional[int] = None,
        height: Optional[int] = None,
        dt: Optional[datetime] = None,
    ) -> Optional[bytes]:
        """Gets snapshot from the package camera.

        Datetime of screenshot is approximate. It may be +/- a few seconds.
        """

        if not self.feature_flags.has_package_camera:
            raise BadRequest("Device does not have package camera")

        if not self.api.bootstrap.auth_user.can(
            ModelType.CAMERA,
            PermissionNode.READ_MEDIA,
            self,
        ):
            raise NotAuthorized(
                f"Do not have permission to read media for camera: {self.id}",
            )

        if height is None and width is None and self.package_camera_channel is not None:
            height = self.package_camera_channel.height

        return await self.api.get_package_camera_snapshot(self.id, width, height, dt=dt)

    async def get_video(
        self,
        start: datetime,
        end: datetime,
        channel_index: int = 0,
        output_file: Optional[Path] = None,
        iterator_callback: Optional[IteratorCallback] = None,
        progress_callback: Optional[ProgressCallback] = None,
        chunk_size: int = 65536,
        fps: Optional[int] = None,
    ) -> Optional[bytes]:
        """Exports MP4 video from a given camera at a specific time.

        Start/End of video export are approximate. It may be +/- a few seconds.

        It is recommended to provide a output file or progress callback for larger
        video clips, otherwise the full video must be downloaded to memory before
        being written.

        Providing the `fps` parameter creates a "timelapse" export wtih the given FPS
        value. Protect app gives the options for 60x (fps=4), 120x (fps=8), 300x
        (fps=20), and 600x (fps=40).
        """

        if not self.api.bootstrap.auth_user.can(
            ModelType.CAMERA,
            PermissionNode.READ_MEDIA,
            self,
        ):
            raise NotAuthorized(
                f"Do not have permission to read media for camera: {self.id}",
            )

        return await self.api.get_camera_video(
            self.id,
            start,
            end,
            channel_index,
            output_file=output_file,
            iterator_callback=iterator_callback,
            progress_callback=progress_callback,
            chunk_size=chunk_size,
            fps=fps,
        )

    async def set_recording_mode(self, mode: RecordingMode) -> None:
        """Sets recording mode on camera"""

        def callback() -> None:
            self.recording_settings.mode = mode

        await self.queue_update(callback)

    async def set_ir_led_model(self, mode: IRLEDMode) -> None:
        """Sets IR LED mode on camera"""

        if not self.feature_flags.has_led_ir:
            raise BadRequest("Camera does not have an LED IR")

        def callback() -> None:
            self.isp_settings.ir_led_mode = mode

        await self.queue_update(callback)

    async def set_icr_custom_lux(self, value: ICRLuxValue) -> None:
        """Set ICRCustomValue from lux value."""

        if not self.feature_flags.has_led_ir:
            raise BadRequest("Camera does not have an LED IR")

        icr_value = 0
        for index, threshold in enumerate(LUX_MAPPING_VALUES):
            if value >= threshold:
                icr_value = 10 - index
                break

        def callback() -> None:
            self.isp_settings.icr_custom_value = cast(ICRCustomValue, icr_value)

        await self.queue_update(callback)

    @property
    def is_ir_led_slider_enabled(self) -> bool:
        """Return if IR LED custom slider is enabled."""

        return (
            self.feature_flags.has_led_ir
            and self.isp_settings.ir_led_mode == IRLEDMode.CUSTOM
        )

    async def set_status_light(self, enabled: bool) -> None:
        """Sets status indicicator light on camera"""

        if not self.feature_flags.has_led_status:
            raise BadRequest("Camera does not have status light")

        def callback() -> None:
            self.led_settings.is_enabled = enabled
            self.led_settings.blink_rate = 0

        await self.queue_update(callback)

    async def set_hdr(self, enabled: bool) -> None:
        """Sets HDR (High Dynamic Range) on camera"""

        warnings.warn(
            "set_hdr is deprecated and replaced with set_hdr_mode for versions of UniFi Protect v3.0+",
            DeprecationWarning,
            stacklevel=2,
        )

        if not self.feature_flags.has_hdr:
            raise BadRequest("Camera does not have HDR")

        def callback() -> None:
            self.hdr_mode = enabled

        await self.queue_update(callback)

    async def set_hdr_mode(self, mode: Literal["auto", "off", "always"]) -> None:
        """Sets HDR mode similar to how Protect interface works."""

        if not self.feature_flags.has_hdr:
            raise BadRequest("Camera does not have HDR")

        def callback() -> None:
            if mode == "off":
                self.hdr_mode = False
                if self.isp_settings.hdr_mode is not None:
                    self.isp_settings.hdr_mode = HDRMode.NORMAL
            else:
                self.hdr_mode = True
                if self.isp_settings.hdr_mode is not None:
                    self.isp_settings.hdr_mode = (
                        HDRMode.NORMAL if mode == "auto" else HDRMode.ALWAYS_ON
                    )

        await self.queue_update(callback)

    async def set_color_night_vision(self, enabled: bool) -> None:
        """Sets Color Night Vision on camera"""

        if not self.has_color_night_vision:
            raise BadRequest("Camera does not have Color Night Vision")

        def callback() -> None:
            self.isp_settings.is_color_night_vision_enabled = enabled

        await self.queue_update(callback)

    async def set_video_mode(self, mode: VideoMode) -> None:
        """Sets video mode on camera"""

        if mode not in self.feature_flags.video_modes:
            raise BadRequest(f"Camera does not have {mode}")

        def callback() -> None:
            self.video_mode = mode

        await self.queue_update(callback)

    async def set_camera_zoom(self, level: int) -> None:
        """Sets zoom level for camera"""

        if not self.feature_flags.can_optical_zoom:
            raise BadRequest("Camera cannot optical zoom")

        def callback() -> None:
            self.isp_settings.zoom_position = PercentInt(level)

        await self.queue_update(callback)

    async def set_wdr_level(self, level: int) -> None:
        """Sets WDR (Wide Dynamic Range) on camera"""

        if self.feature_flags.has_hdr:
            raise BadRequest("Cannot set WDR on cameras with HDR")

        def callback() -> None:
            self.isp_settings.wdr = WDRLevel(level)

        await self.queue_update(callback)

    async def set_mic_volume(self, level: int) -> None:
        """Sets the mic sensitivity level on camera"""

        if not self.feature_flags.has_mic:
            raise BadRequest("Camera does not have mic")

        def callback() -> None:
            self.mic_volume = PercentInt(level)

        await self.queue_update(callback)

    async def set_speaker_volume(self, level: int) -> None:
        """Sets the speaker sensitivity level on camera. Requires camera to have speakers"""

        if not self.feature_flags.has_speaker:
            raise BadRequest("Camera does not have speaker")

        def callback() -> None:
            self.speaker_settings.volume = PercentInt(level)

        await self.queue_update(callback)

    async def set_chime_type(self, chime_type: ChimeType) -> None:
        """Sets chime type for doorbell. Requires camera to be a doorbell"""

        await self.set_chime_duration(timedelta(milliseconds=chime_type.value))

    async def set_chime_duration(self, duration: timedelta | float) -> None:
        """Sets chime duration for doorbell. Requires camera to be a doorbell"""

        if not self.feature_flags.has_chime:
            raise BadRequest("Camera does not have a chime")

        if isinstance(duration, (float, int)):
            if duration < 0:
                raise BadRequest("Chime duration must be a positive number of seconds")
            duration_td = timedelta(seconds=duration)
        else:
            duration_td = duration

        if duration_td.total_seconds() > 10:
            raise BadRequest("Chime duration is too long")

        def callback() -> None:
            self.chime_duration = duration_td

        await self.queue_update(callback)

    async def set_system_sounds(self, enabled: bool) -> None:
        """Sets system sound playback through speakers. Requires camera to have speakers"""

        if not self.feature_flags.has_speaker:
            raise BadRequest("Camera does not have speaker")

        def callback() -> None:
            self.speaker_settings.are_system_sounds_enabled = enabled

        await self.queue_update(callback)

    async def set_osd_name(self, enabled: bool) -> None:
        """Sets whether camera name is in the On Screen Display"""

        def callback() -> None:
            self.osd_settings.is_name_enabled = enabled

        await self.queue_update(callback)

    async def set_osd_date(self, enabled: bool) -> None:
        """Sets whether current date is in the On Screen Display"""

        def callback() -> None:
            self.osd_settings.is_date_enabled = enabled

        await self.queue_update(callback)

    async def set_osd_logo(self, enabled: bool) -> None:
        """Sets whether the UniFi logo is in the On Screen Display"""

        def callback() -> None:
            self.osd_settings.is_logo_enabled = enabled

        await self.queue_update(callback)

    async def set_osd_bitrate(self, enabled: bool) -> None:
        """Sets whether camera bitrate is in the On Screen Display"""

        def callback() -> None:
            # mismatch between UI internal data structure debug = bitrate data
            self.osd_settings.is_debug_enabled = enabled

        await self.queue_update(callback)

    async def set_smart_detect_types(self, types: list[SmartDetectObjectType]) -> None:
        """Sets current enabled smart detection types. Requires camera to have smart detection"""

        if not self.feature_flags.has_smart_detect:
            raise BadRequest("Camera does not have a smart detections")

        def callback() -> None:
            self.smart_detect_settings.object_types = types

        await self.queue_update(callback)

    async def set_smart_audio_detect_types(
        self,
        types: list[SmartDetectAudioType],
    ) -> None:
        """Sets current enabled smart audio detection types. Requires camera to have smart detection"""

        if not self.feature_flags.has_smart_detect:
            raise BadRequest("Camera does not have a smart detections")

        def callback() -> None:
            self.smart_detect_settings.audio_types = types

        await self.queue_update(callback)

    async def _set_object_detect(
        self,
        obj_to_mod: SmartDetectObjectType,
        enabled: bool,
    ) -> None:
        if obj_to_mod not in self.feature_flags.smart_detect_types:
            raise BadRequest(f"Camera does not support the {obj_to_mod} detection type")

        def callback() -> None:
            objects = self.smart_detect_settings.object_types
            if enabled:
                if obj_to_mod not in objects:
                    objects = [*objects, obj_to_mod]
                    objects.sort()
            elif obj_to_mod in objects:
                objects.remove(obj_to_mod)
            self.smart_detect_settings.object_types = objects

        await self.queue_update(callback)

    async def _set_audio_detect(
        self,
        obj_to_mod: SmartDetectAudioType,
        enabled: bool,
    ) -> None:
        if (
            self.feature_flags.smart_detect_audio_types is None
            or obj_to_mod not in self.feature_flags.smart_detect_audio_types
        ):
            raise BadRequest(f"Camera does not support the {obj_to_mod} detection type")

        def callback() -> None:
            objects = self.smart_detect_settings.audio_types or []
            if enabled:
                if obj_to_mod not in objects:
                    objects = [*objects, obj_to_mod]
                    objects.sort()
            elif obj_to_mod in objects:
                objects.remove(obj_to_mod)
            self.smart_detect_settings.audio_types = objects

        await self.queue_update(callback)

    async def set_lcd_text(
        self,
        text_type: Optional[DoorbellMessageType],
        text: Optional[str] = None,
        reset_at: Union[None, datetime, DEFAULT_TYPE] = None,
    ) -> None:
        """Sets doorbell LCD text. Requires camera to be doorbell"""

        if not self.feature_flags.has_lcd_screen:
            raise BadRequest("Camera does not have an LCD screen")

        if text_type is None:
            async with self._update_lock:
                await asyncio.sleep(
                    0,
                )  # yield to the event loop once we have the lock to process any pending updates
                data_before_changes = self.dict_with_excludes()
                self.lcd_message = None
                # UniFi Protect bug: clearing LCD text message does _not_ emit a WS message
                await self.save_device(data_before_changes, force_emit=True)
                return

        if text_type != DoorbellMessageType.CUSTOM_MESSAGE:
            if text is not None:
                raise BadRequest("Can only set text if text_type is CUSTOM_MESSAGE")
            text = text_type.value.replace("_", " ")

        if reset_at == DEFAULT:
            reset_at = (
                utc_now()
                + self.api.bootstrap.nvr.doorbell_settings.default_message_reset_timeout
            )

        def callback() -> None:
            self.lcd_message = LCDMessage(  # type: ignore[call-arg]
                api=self._api,
                type=text_type,
                text=text,  # type: ignore[arg-type]
                reset_at=reset_at,  # type: ignore[arg-type]
            )

        await self.queue_update(callback)

    async def set_privacy(
        self,
        enabled: bool,
        mic_level: Optional[int] = None,
        recording_mode: Optional[RecordingMode] = None,
    ) -> None:
        """Adds/removes a privacy zone that blacks out the whole camera"""

        if not self.feature_flags.has_privacy_mask:
            raise BadRequest("Camera does not allow privacy zones")

        def callback() -> None:
            if enabled:
                self.add_privacy_zone()
            else:
                self.remove_privacy_zone()

            if mic_level is not None:
                self.mic_volume = PercentInt(mic_level)

            if recording_mode is not None:
                self.recording_settings.mode = recording_mode

        await self.queue_update(callback)

    async def set_person_track(self, enabled: bool) -> None:
        """Sets person tracking on camera"""

        if not self.feature_flags.is_ptz:
            raise BadRequest("Camera does not support person tracking")

        def callback() -> None:
            self.smart_detect_settings.auto_tracking_object_types = (
                [SmartDetectObjectType.PERSON] if enabled else []
            )

        await self.queue_update(callback)

    def create_talkback_stream(
        self,
        content_url: str,
        ffmpeg_path: Optional[Path] = None,
    ) -> TalkbackStream:
        """Creates a subprocess to play audio to a camera through its speaker.

        Requires ffmpeg to use.

        Args:
        ----
            content_url: Either a URL accessible by python or a path to a file (ffmepg's `-i` parameter)
            ffmpeg_path: Optional path to ffmpeg binary

        Use either `await stream.run_until_complete()` or `await stream.start()` to start subprocess command
        after getting the stream.

        `.play_audio()` is a helper that wraps this method and automatically runs the subprocess as well
        """

        if self.talkback_stream is not None and self.talkback_stream.is_running:
            raise BadRequest("Camera is already playing audio")

        self.talkback_stream = TalkbackStream(self, content_url, ffmpeg_path)
        return self.talkback_stream

    async def play_audio(
        self,
        content_url: str,
        ffmpeg_path: Optional[Path] = None,
        blocking: bool = True,
    ) -> None:
        """Plays audio to a camera through its speaker.

        Requires ffmpeg to use.

        Args:
        ----
            content_url: Either a URL accessible by python or a path to a file (ffmepg's `-i` parameter)
            ffmpeg_path: Optional path to ffmpeg binary
            blocking: Awaits stream completion and logs stdout/stderr
        """

        stream = self.create_talkback_stream(content_url, ffmpeg_path)
        await stream.start()

        if blocking:
            await self.wait_until_audio_completes()

    async def wait_until_audio_completes(self) -> None:
        """Awaits stream completion of audio and logs stdout/stderr."""

        stream = self.talkback_stream
        if stream is None:
            raise StreamError("No audio playing to wait for")

        await stream.run_until_complete()

        _LOGGER.debug("ffmpeg stdout:\n%s", "\n".join(stream.stdout))
        _LOGGER.debug("ffmpeg stderr:\n%s", "\n".join(stream.stderr))
        if stream.is_error:
            error = "\n".join(stream.stderr)
            raise StreamError("Error while playing audio (ffmpeg): \n" + error)

    async def stop_audio(self) -> None:
        """Stop currently playing audio."""
        stream = self.talkback_stream
        if stream is None:
            raise StreamError("No audio playing to stop")

        await stream.stop()

    def can_read_media(self, user: User) -> bool:
        if self.model is None:
            return True

        return user.can(self.model, PermissionNode.READ_MEDIA, self)

    def can_delete_media(self, user: User) -> bool:
        if self.model is None:
            return True

        return user.can(self.model, PermissionNode.DELETE_MEDIA, self)


class Viewer(ProtectAdoptableDeviceModel):
    stream_limit: int
    software_version: str
    liveview_id: str

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "liveview": "liveviewId"}

    @classmethod
    @cache
    def _get_read_only_fields(cls) -> set[str]:
        return super()._get_read_only_fields() | {"softwareVersion"}

    @property
    def liveview(self) -> Optional[Liveview]:
        # user may not have permission to see the liveview
        return self.api.bootstrap.liveviews.get(self.liveview_id)

    async def set_liveview(self, liveview: Liveview) -> None:
        """Sets the liveview current set for the viewer

        Args:
        ----
            liveview: The liveview you want to set
        """

        if self._api is not None and liveview.id not in self._api.bootstrap.liveviews:
            raise BadRequest("Unknown liveview")

        async with self._update_lock:
            await asyncio.sleep(
                0,
            )  # yield to the event loop once we have the lock to process any pending updates
            data_before_changes = self.dict_with_excludes()
            self.liveview_id = liveview.id
            # UniFi Protect bug: changing the liveview does _not_ emit a WS message
            await self.save_device(data_before_changes, force_emit=True)


class Bridge(ProtectAdoptableDeviceModel):
    platform: str


class SensorSettingsBase(ProtectBaseObject):
    is_enabled: bool


class SensorThresholdSettings(SensorSettingsBase):
    margin: float  # read only
    # "safe" thresholds for alerting
    # anything below/above will trigger alert
    low_threshold: Optional[float]
    high_threshold: Optional[float]


class SensorSensitivitySettings(SensorSettingsBase):
    sensitivity: PercentInt


class SensorBatteryStatus(ProtectBaseObject):
    percentage: Optional[PercentInt]
    is_low: bool


class SensorStat(ProtectBaseObject):
    value: Optional[float]
    status: SensorStatusType


class SensorStats(ProtectBaseObject):
    light: SensorStat
    humidity: SensorStat
    temperature: SensorStat


class Sensor(ProtectAdoptableDeviceModel):
    alarm_settings: SensorSettingsBase
    alarm_triggered_at: Optional[datetime]
    battery_status: SensorBatteryStatus
    camera_id: Optional[str]
    humidity_settings: SensorThresholdSettings
    is_motion_detected: bool
    is_opened: bool
    leak_detected_at: Optional[datetime]
    led_settings: SensorSettingsBase
    light_settings: SensorThresholdSettings
    motion_detected_at: Optional[datetime]
    motion_settings: SensorSensitivitySettings
    open_status_changed_at: Optional[datetime]
    stats: SensorStats
    tampering_detected_at: Optional[datetime]
    temperature_settings: SensorThresholdSettings
    mount_type: MountType

    # not directly from UniFi
    last_motion_event_id: Optional[str] = None
    last_contact_event_id: Optional[str] = None
    last_value_event_id: Optional[str] = None
    last_alarm_event_id: Optional[str] = None
    extreme_value_detected_at: Optional[datetime] = None
    _tamper_timeout: Optional[datetime] = PrivateAttr(None)
    _alarm_timeout: Optional[datetime] = PrivateAttr(None)

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "camera": "cameraId"}

    @classmethod
    @cache
    def _get_read_only_fields(cls) -> set[str]:
        return super()._get_read_only_fields() | {
            "batteryStatus",
            "isMotionDetected",
            "leakDetectedAt",
            "tamperingDetectedAt",
            "isOpened",
            "openStatusChangedAt",
            "alarmTriggeredAt",
            "motionDetectedAt",
            "stats",
        }

    def unifi_dict(
        self,
        data: Optional[dict[str, Any]] = None,
        exclude: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "lastMotionEventId" in data:
            del data["lastMotionEventId"]
        if "lastContactEventId" in data:
            del data["lastContactEventId"]
        if "lastValueEventId" in data:
            del data["lastValueEventId"]
        if "lastAlarmEventId" in data:
            del data["lastAlarmEventId"]
        if "extremeValueDetectedAt" in data:
            del data["extremeValueDetectedAt"]

        return data

    @property
    def camera(self) -> Optional[Camera]:
        """Paired Camera will always be none if no camera is paired"""

        if self.camera_id is None:
            return None

        return self.api.bootstrap.cameras[self.camera_id]

    @property
    def is_tampering_detected(self) -> bool:
        return self.tampering_detected_at is not None

    @property
    def is_alarm_detected(self) -> bool:
        if self._alarm_timeout is None:
            return False
        return utc_now() < self._alarm_timeout

    @property
    def is_contact_sensor_enabled(self) -> bool:
        return self.mount_type in {MountType.DOOR, MountType.WINDOW, MountType.GARAGE}

    @property
    def is_motion_sensor_enabled(self) -> bool:
        return self.mount_type != MountType.LEAK and self.motion_settings.is_enabled

    @property
    def is_alarm_sensor_enabled(self) -> bool:
        return self.mount_type != MountType.LEAK and self.alarm_settings.is_enabled

    @property
    def is_light_sensor_enabled(self) -> bool:
        return self.mount_type != MountType.LEAK and self.light_settings.is_enabled

    @property
    def is_temperature_sensor_enabled(self) -> bool:
        return (
            self.mount_type != MountType.LEAK and self.temperature_settings.is_enabled
        )

    @property
    def is_humidity_sensor_enabled(self) -> bool:
        return self.mount_type != MountType.LEAK and self.humidity_settings.is_enabled

    @property
    def is_leak_sensor_enabled(self) -> bool:
        return self.mount_type is MountType.LEAK

    def set_alarm_timeout(self) -> None:
        self._alarm_timeout = utc_now() + EVENT_PING_INTERVAL
        self._event_callback_ping()

    @property
    def last_motion_event(self) -> Optional[Event]:
        if self.last_motion_event_id is None:
            return None

        return self.api.bootstrap.events.get(self.last_motion_event_id)

    @property
    def last_contact_event(self) -> Optional[Event]:
        if self.last_contact_event_id is None:
            return None

        return self.api.bootstrap.events.get(self.last_contact_event_id)

    @property
    def last_value_event(self) -> Optional[Event]:
        if self.last_value_event_id is None:
            return None

        return self.api.bootstrap.events.get(self.last_value_event_id)

    @property
    def last_alarm_event(self) -> Optional[Event]:
        if self.last_alarm_event_id is None:
            return None

        return self.api.bootstrap.events.get(self.last_alarm_event_id)

    @property
    def is_leak_detected(self) -> bool:
        return self.leak_detected_at is not None

    async def set_status_light(self, enabled: bool) -> None:
        """Sets the status indicator light for the sensor"""

        def callback() -> None:
            self.led_settings.is_enabled = enabled

        await self.queue_update(callback)

    async def set_mount_type(self, mount_type: MountType) -> None:
        """Sets current mount type for sensor"""

        def callback() -> None:
            self.mount_type = mount_type

        await self.queue_update(callback)

    async def set_motion_status(self, enabled: bool) -> None:
        """Sets the motion detection type for the sensor"""

        def callback() -> None:
            self.motion_settings.is_enabled = enabled

        await self.queue_update(callback)

    async def set_motion_sensitivity(self, sensitivity: int) -> None:
        """Sets the motion sensitivity for the sensor"""

        def callback() -> None:
            self.motion_settings.sensitivity = PercentInt(sensitivity)

        await self.queue_update(callback)

    async def set_temperature_status(self, enabled: bool) -> None:
        """Sets the temperature detection type for the sensor"""

        def callback() -> None:
            self.temperature_settings.is_enabled = enabled

        await self.queue_update(callback)

    async def set_temperature_safe_range(self, low: float, high: float) -> None:
        """Sets the temperature safe range for the sensor"""

        if low < 0.0:
            raise BadRequest("Minimum value is 0°C")
        if high > 45.0:
            raise BadRequest("Maximum value is 45°C")
        if high <= low:
            raise BadRequest("High value must be above low value")

        def callback() -> None:
            self.temperature_settings.low_threshold = low
            self.temperature_settings.high_threshold = high

        await self.queue_update(callback)

    async def remove_temperature_safe_range(self) -> None:
        """Removes the temperature safe range for the sensor"""

        def callback() -> None:
            self.temperature_settings.low_threshold = None
            self.temperature_settings.high_threshold = None

        await self.queue_update(callback)

    async def set_humidity_status(self, enabled: bool) -> None:
        """Sets the humidity detection type for the sensor"""

        def callback() -> None:
            self.humidity_settings.is_enabled = enabled

        await self.queue_update(callback)

    async def set_humidity_safe_range(self, low: float, high: float) -> None:
        """Sets the humidity safe range for the sensor"""

        if low < 1.0:
            raise BadRequest("Minimum value is 1%")
        if high > 99.0:
            raise BadRequest("Maximum value is 99%")
        if high <= low:
            raise BadRequest("High value must be above low value")

        def callback() -> None:
            self.humidity_settings.low_threshold = low
            self.humidity_settings.high_threshold = high

        await self.queue_update(callback)

    async def remove_humidity_safe_range(self) -> None:
        """Removes the humidity safe range for the sensor"""

        def callback() -> None:
            self.humidity_settings.low_threshold = None
            self.humidity_settings.high_threshold = None

        await self.queue_update(callback)

    async def set_light_status(self, enabled: bool) -> None:
        """Sets the light detection type for the sensor"""

        def callback() -> None:
            self.light_settings.is_enabled = enabled

        await self.queue_update(callback)

    async def set_light_safe_range(self, low: float, high: float) -> None:
        """Sets the light safe range for the sensor"""

        if low < 1.0:
            raise BadRequest("Minimum value is 1 lux")
        if high > 1000.0:
            raise BadRequest("Maximum value is 1000 lux")
        if high <= low:
            raise BadRequest("High value must be above low value")

        def callback() -> None:
            self.light_settings.low_threshold = low
            self.light_settings.high_threshold = high

        await self.queue_update(callback)

    async def remove_light_safe_range(self) -> None:
        """Removes the light safe range for the sensor"""

        def callback() -> None:
            self.light_settings.low_threshold = None
            self.light_settings.high_threshold = None

        await self.queue_update(callback)

    async def set_alarm_status(self, enabled: bool) -> None:
        """Sets the alarm detection type for the sensor"""

        def callback() -> None:
            self.alarm_settings.is_enabled = enabled

        await self.queue_update(callback)

    async def set_paired_camera(self, camera: Optional[Camera]) -> None:
        """Sets the camera paired with the sensor"""

        def callback() -> None:
            if camera is None:
                self.camera_id = None
            else:
                self.camera_id = camera.id

        await self.queue_update(callback)

    async def clear_tamper(self) -> None:
        """Clears tamper status for sensor"""

        if not self.api.bootstrap.auth_user.can(
            ModelType.SENSOR,
            PermissionNode.WRITE,
            self,
        ):
            raise NotAuthorized(
                f"Do not have permission to clear tamper for sensor: {self.id}",
            )
        await self.api.clear_tamper_sensor(self.id)


class Doorlock(ProtectAdoptableDeviceModel):
    credentials: Optional[str]
    lock_status: LockStatusType
    enable_homekit: bool
    auto_close_time: timedelta
    led_settings: SensorSettingsBase
    battery_status: SensorBatteryStatus
    camera_id: Optional[str]
    has_homekit: bool
    private_token: str

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "camera": "cameraId",
            "autoCloseTimeMs": "autoCloseTime",
        }

    @classmethod
    @cache
    def _get_read_only_fields(cls) -> set[str]:
        return super()._get_read_only_fields() | {
            "credentials",
            "lockStatus",
            "batteryStatus",
        }

    @classmethod
    def unifi_dict_to_dict(cls, data: dict[str, Any]) -> dict[str, Any]:
        if "autoCloseTimeMs" in data and not isinstance(
            data["autoCloseTimeMs"],
            timedelta,
        ):
            data["autoCloseTimeMs"] = timedelta(milliseconds=data["autoCloseTimeMs"])

        return super().unifi_dict_to_dict(data)

    @property
    def camera(self) -> Optional[Camera]:
        """Paired Camera will always be none if no camera is paired"""

        if self.camera_id is None:
            return None

        return self.api.bootstrap.cameras[self.camera_id]

    async def set_paired_camera(self, camera: Optional[Camera]) -> None:
        """Sets the camera paired with the sensor"""

        def callback() -> None:
            if camera is None:
                self.camera_id = None
            else:
                self.camera_id = camera.id

        await self.queue_update(callback)

    async def set_status_light(self, enabled: bool) -> None:
        """Sets the status indicator light for the doorlock"""

        def callback() -> None:
            self.led_settings.is_enabled = enabled

        await self.queue_update(callback)

    async def set_auto_close_time(self, duration: timedelta) -> None:
        """Sets the auto-close time for doorlock. 0 seconds = disabled."""

        if duration > timedelta(hours=1):
            raise BadRequest("Max duration is 1 hour")

        def callback() -> None:
            self.auto_close_time = duration

        await self.queue_update(callback)

    async def close_lock(self) -> None:
        """Close doorlock (lock)"""

        if self.lock_status != LockStatusType.OPEN:
            raise BadRequest("Lock is not open")

        await self.api.close_lock(self.id)

    async def open_lock(self) -> None:
        """Open doorlock (unlock)"""

        if self.lock_status != LockStatusType.CLOSED:
            raise BadRequest("Lock is not closed")

        await self.api.open_lock(self.id)

    async def calibrate(self) -> None:
        """Calibrate the doorlock.

        Door must be open and lock unlocked.
        """

        await self.api.calibrate_lock(self.id)


class ChimeFeatureFlags(ProtectBaseObject):
    has_wifi: bool
    # 2.9.20+
    has_https_client_ota: Optional[bool] = None

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "hasHttpsClientOTA": "hasHttpsClientOta"}


class RingSetting(ProtectBaseObject):
    camera_id: str
    repeat_times: RepeatTimes
    track_no: int
    volume: int

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "camera": "cameraId"}

    @property
    def camera(self) -> Optional[Camera]:
        """Paired Camera will always be none if no camera is paired"""

        if self.camera_id is None:
            return None

        return self.api.bootstrap.cameras[self.camera_id]


class ChimeTrack(ProtectBaseObject):
    md5: str
    name: str
    state: str
    track_no: int
    volume: int
    size: int

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "track_no": "trackNo"}


class Chime(ProtectAdoptableDeviceModel):
    volume: PercentInt
    is_probing_for_wifi: bool
    last_ring: Optional[datetime]
    is_wireless_uplink_enabled: bool
    camera_ids: list[str]
    # requires 2.6.17+
    ap_mgmt_ip: Optional[IPv4Address] = None
    # requires 2.7.15+
    feature_flags: Optional[ChimeFeatureFlags] = None
    # requires 2.8.22+
    user_configured_ap: Optional[bool] = None
    # requires 3.0.22+
    has_https_client_ota: Optional[bool] = None
    platform: Optional[str] = None
    repeat_times: Optional[RepeatTimes] = None
    track_no: Optional[int] = None
    ring_settings: list[RingSetting] = []
    speaker_track_list: list[ChimeTrack] = []

    # TODO: used for adoption
    # apMac  read only
    # apRssi  read only
    # elementInfo  read only

    @classmethod
    @cache
    def _get_unifi_remaps(cls) -> dict[str, str]:
        return {**super()._get_unifi_remaps(), "hasHttpsClientOTA": "hasHttpsClientOta"}

    @classmethod
    @cache
    def _get_read_only_fields(cls) -> set[str]:
        return super()._get_read_only_fields() | {"isProbingForWifi", "lastRing"}

    @property
    def cameras(self) -> list[Camera]:
        """Paired Cameras for chime"""

        if len(self.camera_ids) == 0:
            return []
        return [self.api.bootstrap.cameras[c] for c in self.camera_ids]

    async def set_volume(self, level: int) -> None:
        """Set the volume on chime."""

        old_value = self.volume
        new_value = PercentInt(level)

        def callback() -> None:
            self.volume = new_value
            for setting in self.ring_settings:
                if setting.volume == old_value:
                    setting.volume = new_value

        await self.queue_update(callback)

    async def set_volume_for_camera(self, camera: Camera, level: int) -> None:
        """Set the volume on chime for specific camera."""

        def callback() -> None:
            handled = False
            for setting in self.ring_settings:
                if setting.camera_id == camera.id:
                    setting.volume = cast(PercentInt, level)
                    handled = True
                    break

            if not handled:
                raise BadRequest("Camera %s is not paired with chime", camera.id)

        await self.queue_update(callback)

    async def add_camera(self, camera: Camera) -> None:
        """Adds new paired camera to chime"""

        if not camera.feature_flags.is_doorbell:
            raise BadRequest("Camera does not have a chime")

        if camera.id in self.camera_ids:
            raise BadRequest("Camera is already paired")

        def callback() -> None:
            self.camera_ids.append(camera.id)

        await self.queue_update(callback)

    async def remove_camera(self, camera: Camera) -> None:
        """Removes paired camera from chime"""

        if camera.id not in self.camera_ids:
            raise BadRequest("Camera is not paired")

        def callback() -> None:
            self.camera_ids.remove(camera.id)

        await self.queue_update(callback)

    async def play(
        self,
        *,
        volume: int | None = None,
        repeat_times: int | None = None,
    ) -> None:
        """Plays chime tone"""

        await self.api.play_speaker(self.id, volume=volume, repeat_times=repeat_times)

    async def play_buzzer(self) -> None:
        """Plays chime buzzer"""

        await self.api.play_buzzer(self.id)

    async def set_repeat_times(self, value: int) -> None:
        """Set repeat times on chime."""

        old_value = self.repeat_times

        def callback() -> None:
            self.repeat_times = cast(RepeatTimes, value)
            for setting in self.ring_settings:
                if setting.repeat_times == old_value:
                    setting.repeat_times = cast(RepeatTimes, value)

        await self.queue_update(callback)

    async def set_repeat_times_for_camera(
        self,
        camera: Camera,
        value: int,
    ) -> None:
        """Set repeat times on chime for specific camera."""

        def callback() -> None:
            handled = False
            for setting in self.ring_settings:
                if setting.camera_id == camera.id:
                    setting.repeat_times = cast(RepeatTimes, value)
                    handled = True
                    break

            if not handled:
                raise BadRequest("Camera %s is not paired with chime", camera.id)

        await self.queue_update(callback)
