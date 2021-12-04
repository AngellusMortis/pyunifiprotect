"""Unifi Protect Data."""
from __future__ import annotations

from datetime import datetime, timedelta
from ipaddress import IPv4Address
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple, Union
from uuid import UUID

from pyunifiprotect.data.base import (
    ProtectAdoptableDeviceModel,
    ProtectBaseObject,
    ProtectMotionDeviceModel,
)
from pyunifiprotect.data.types import (
    DEFAULT,
    DEFAULT_TYPE,
    ChimeDuration,
    Color,
    DoorbellMessageType,
    IRLEDMode,
    LEDLevel,
    LightModeEnableType,
    LightModeType,
    Percent,
    PercentInt,
    RecordingMode,
    SmartDetectObjectType,
    VideoMode,
    WDRLevel,
)
from pyunifiprotect.exceptions import BadRequest, StreamError
from pyunifiprotect.stream import TalkbackStream
from pyunifiprotect.utils import (
    from_js_time,
    is_debug,
    process_datetime,
    round_decimal,
    serialize_point,
    to_js_time,
    utc_now,
)

if TYPE_CHECKING:
    from pyunifiprotect.data.nvr import Event, Liveview

PRIVACY_ZONE_NAME = "pyufp_privacy_zone"

_LOGGER = logging.getLogger(__name__)


class LightDeviceSettings(ProtectBaseObject):
    # Status LED
    is_indicator_enabled: bool
    # Brightness
    led_level: LEDLevel
    # unknown
    lux_sensitivity: str
    pir_duration: timedelta
    pir_sensitivity: PercentInt

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
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
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {**super()._get_unifi_remaps(), "camera": "cameraId"}

    @property
    def camera(self) -> Optional[Camera]:
        """Paired Camera will always be none if no camera is paired"""

        if self.camera_id is None:
            return None

        return self.api.bootstrap.cameras[self.camera_id]

    async def set_status_light(self, enabled: bool) -> None:
        """Sets the status indicator light for the light"""

        self.light_device_settings.is_indicator_enabled = enabled
        await self.save_device()

    async def set_led_level(self, led_level: int) -> None:
        """Sets the LED level for the light"""

        self.light_device_settings.led_level = LEDLevel(led_level)
        await self.save_device()

    async def set_light(self, enabled: bool, led_level: Optional[int] = None) -> None:
        """Force turns on/off the light"""

        self.light_on_settings.is_led_force_on = enabled
        if led_level is not None:
            self.light_device_settings.led_level = LEDLevel(led_level)

        await self.save_device()

    async def set_sensitivity(self, sensitivity: int) -> None:
        """Sets motion sensitivity"""

        self.light_device_settings.pir_sensitivity = PercentInt(sensitivity)
        await self.save_device()

    async def set_duration(self, duration: timedelta) -> None:
        """Sets motion sensitivity"""

        if duration.total_seconds() < 15 or duration.total_seconds() > 900:
            raise BadRequest("Duration outside of 15s to 900s range")

        self.light_device_settings.pir_duration = duration
        await self.save_device()

    async def set_light_settings(
        self,
        mode: LightModeType,
        enable_at: Optional[LightModeEnableType] = None,
        duration: Optional[timedelta] = None,
        sensitivity: Optional[int] = None,
    ) -> None:
        """Updates various Light settings.

        Args:

        * `mode`: Light trigger mode
        * `enable_at`: Then the light automatically turns on by itself
        * `duration`: How long the light should remain on after motion, must be timedelta between 15s and 900s
        * `sensitivity`: PIR Motion sensitivity
        """

        self.light_mode_settings.mode = mode
        if enable_at is not None:
            self.light_mode_settings.enable_at = enable_at
        if duration is not None:
            if duration.total_seconds() < 15 or duration.total_seconds() > 900:
                raise BadRequest("Duration outside of 15s to 900s range")

            self.light_device_settings.pir_duration = duration
        if sensitivity is not None:
            self.light_device_settings.pir_sensitivity = PercentInt(sensitivity)

        await self.save_device()


class EventStats(ProtectBaseObject):
    today: int
    average: int
    last_days: List[int]
    recent_hours: List[int] = []

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        data = super().unifi_dict_to_dict(data)

        if "recent_hours" not in data:
            data["recent_hours"] = []

        return data

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "recentHours" in data and len(data["recentHours"]) == 0:
            del data["recentHours"]

        return data


class CameraEventStats(ProtectBaseObject):
    motion: EventStats
    smart: EventStats


class CameraChannel(ProtectBaseObject):
    id: int
    video_id: str
    name: str
    enabled: bool
    is_rtsp_enabled: bool
    rtsp_alias: Optional[str]
    width: int
    height: int
    fps: int
    bitrate: int
    min_bitrate: int
    max_bitrate: int
    min_client_adaptive_bit_rate: int
    min_motion_adaptive_bit_rate: int
    fps_values: List[int]
    idr_interval: int

    @property
    def rtsp_url(self) -> Optional[str]:
        if not self.is_rtsp_enabled or self.rtsp_alias is None:
            return None

        return f"rtsp://{self.api.connection_host}:{self.api.bootstrap.nvr.ports.rtsp}/{self.rtsp_alias}"

    @property
    def rtsps_url(self) -> Optional[str]:
        if not self.is_rtsp_enabled or self.rtsp_alias is None:
            return None

        return f"rtsps://{self.api.connection_host}:{self.api.bootstrap.nvr.ports.rtsps}/{self.rtsp_alias}?enableSrtp"


class ISPSettings(ProtectBaseObject):
    ae_mode: str
    ir_led_mode: IRLEDMode
    ir_led_level: int
    wdr: WDRLevel
    icr_sensitivity: int
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
    focus_mode: str
    focus_position: int
    touch_focus_x: int
    touch_focus_y: int
    zoom_position: PercentInt

    # TODO:
    # mountPosition


class OSDSettings(ProtectBaseObject):
    # Overlay Information
    is_name_enabled: bool
    is_date_enabled: bool
    is_logo_enabled: bool
    is_debug_enabled: bool


class LEDSettings(ProtectBaseObject):
    # Status Light
    is_enabled: bool
    blink_rate: int


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
    geofencing: str
    motion_algorithm: str
    enable_pir_timelapse: bool
    use_new_motion_algorithm: bool

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "prePaddingSecs" in data:
            data["prePadding"] = timedelta(seconds=data.pop("prePaddingSecs"))
        if "postPaddingSecs" in data:
            data["postPadding"] = timedelta(seconds=data.pop("postPaddingSecs"))
        if "minMotionEventTrigger" in data and not isinstance(data["minMotionEventTrigger"], timedelta):
            data["minMotionEventTrigger"] = timedelta(seconds=data["minMotionEventTrigger"])
        if "endMotionEventDelay" in data and not isinstance(data["endMotionEventDelay"], timedelta):
            data["endMotionEventDelay"] = timedelta(seconds=data["endMotionEventDelay"])

        return super().unifi_dict_to_dict(data)

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "prePadding" in data:
            data["prePaddingSecs"] = data.pop("prePadding") // 1000
        if "postPadding" in data:
            data["postPaddingSecs"] = data.pop("postPadding") // 1000
        if "minMotionEventTrigger" in data:
            data["minMotionEventTrigger"] = data.pop("minMotionEventTrigger") // 1000
        if "endMotionEventDelay" in data:
            data["endMotionEventDelay"] = data.pop("endMotionEventDelay") // 1000

        return data


class SmartDetectSettings(ProtectBaseObject):
    object_types: List[SmartDetectObjectType]


class PIRSettings(ProtectBaseObject):
    pir_sensitivity: int
    pir_motion_clip_length: int
    timelapse_frame_interval: int
    timelapse_transfer_interval: int


class LCDMessage(ProtectBaseObject):
    type: DoorbellMessageType
    text: str
    reset_at: Optional[datetime] = None

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
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

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "text" in data:
            data["text"] = self._fix_text(data["text"], data.get("type", self.type.value))
        if "resetAt" in data:
            data["resetAt"] = to_js_time(data["resetAt"])

        return data


class TalkbackSettings(ProtectBaseObject):
    type_fmt: str
    type_in: str
    bind_addr: IPv4Address
    bind_port: int
    filter_addr: Optional[str]
    filter_port: Optional[int]
    channels: int
    sampling_rate: int
    bits_per_sample: int
    quality: int


class WifiStats(ProtectBaseObject):
    channel: Optional[int]
    frequency: Optional[int]
    link_speed_mbps: Optional[str]
    signal_quality: PercentInt
    signal_strength: int


class BatteryStats(ProtectBaseObject):
    percentage: Optional[PercentInt]
    is_charging: bool
    sleep_state: str


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
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "recordingStartLQ": "recordingStartLq",
            "recordingEndLQ": "recordingEndLq",
            "timelapseStartLQ": "timelapseStartLq",
            "timelapseEndLQ": "timelapseEndLq",
        }

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
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
    used: Optional[int]
    rate: Optional[float]

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "rate" not in data:
            data["rate"] = None

        return super().unifi_dict_to_dict(data)

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "rate" in data and data["rate"] is None:
            del data["rate"]

        return data


class CameraStats(ProtectBaseObject):
    rx_bytes: int
    tx_bytes: int
    wifi: WifiStats
    battery: BatteryStats
    video: VideoStats
    storage: Optional[StorageStats]
    wifi_quality: PercentInt
    wifi_strength: int

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "storage" in data and data["storage"] == {}:
            del data["storage"]

        return super().unifi_dict_to_dict(data)

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "storage" in data and data["storage"] is None:
            data["storage"] = {}

        return data


class CameraZone(ProtectBaseObject):
    id: int
    name: str
    color: Color
    points: List[Tuple[Percent, Percent]]

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        data = super().unifi_dict_to_dict(data)

        if not is_debug():
            if "points" in data and isinstance(data["points"], list):
                data["points"] = [(round_decimal(p[0], 4), round_decimal(p[1], 4)) for p in data["points"]]

        return data

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "points" in data:
            data["points"] = [serialize_point(p) for p in data["points"]]

        return data

    @staticmethod
    def create_privacy_zone(zone_id: int) -> CameraZone:
        return CameraZone(
            id=zone_id, name=PRIVACY_ZONE_NAME, color=Color("#85BCEC"), points=[[0, 0], [1, 0], [1, 1], [0, 1]]
        )


class MotionZone(CameraZone):
    sensitivity: PercentInt


class SmartMotionZone(MotionZone):
    object_types: List[SmartDetectObjectType]


class PrivacyMaskCapability(ProtectBaseObject):
    max_masks: int
    rectangle_only: bool


class FeatureFlags(ProtectBaseObject):
    can_adjust_ir_led_level: bool
    can_magic_zoom: bool
    can_optical_zoom: bool
    can_touch_focus: bool
    has_accelerometer: bool
    has_aec: bool
    has_battery: bool
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
    video_modes: List[VideoMode]
    video_mode_max_fps: List[int]
    has_motion_zones: bool
    has_lcd_screen: bool
    smart_detect_types: List[SmartDetectObjectType]
    motion_algorithms: List[str]
    has_square_event_thumbnail: bool
    has_package_camera: bool
    privacy_mask_capability: PrivacyMaskCapability
    has_smart_detect: bool

    # TODO:
    # mountPositions
    # focus
    # pan
    # tilt
    # zoom

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {**super()._get_unifi_remaps(), "hasAutoICROnly": "hasAutoIcrOnly"}

    @property
    def has_highfps(self) -> bool:
        return VideoMode.HIGH_FPS in self.video_modes

    @property
    def has_wdr(self) -> bool:
        return not self.has_hdr


class Camera(ProtectMotionDeviceModel):
    is_deleting: bool
    # Microphone Sensitivity
    mic_volume: PercentInt
    is_mic_enabled: bool
    is_recording: bool
    is_motion_detected: bool
    is_smart_detected: bool
    phy_rate: int
    hdr_mode: bool
    # Recording Quality -> High Frame
    video_mode: VideoMode
    is_probing_for_wifi: bool
    chime_duration: ChimeDuration
    last_ring: Optional[datetime]
    is_live_heatmap_enabled: bool
    anonymous_device_id: UUID
    event_stats: CameraEventStats
    video_reconfiguration_in_progress: bool
    channels: List[CameraChannel]
    isp_settings: ISPSettings
    talkback_settings: TalkbackSettings
    osd_settings: OSDSettings
    led_settings: LEDSettings
    speaker_settings: SpeakerSettings
    recording_settings: RecordingSettings
    smart_detect_settings: SmartDetectSettings
    motion_zones: List[MotionZone]
    privacy_zones: List[CameraZone]
    smart_detect_zones: List[SmartMotionZone]
    stats: CameraStats
    feature_flags: FeatureFlags
    pir_settings: PIRSettings
    lcd_message: Optional[LCDMessage]
    platform: str
    has_speaker: bool
    has_wifi: bool
    audio_bitrate: int
    can_manage: bool
    is_managed: bool
    voltage: Optional[float]

    # TODO:
    # apMac
    # apRssi
    # elementInfo
    # lastPrivacyZonePositionId
    # recordingSchedule
    # smartDetectLines
    # lenses

    # not directly from Unifi
    last_ring_event_id: Optional[str] = None
    last_smart_detect: Optional[datetime] = None
    last_smart_detect_event_id: Optional[str] = None
    talkback_stream: Optional[TalkbackStream] = None

    @classmethod
    def _get_excluded_changed_fields(cls) -> Set[str]:
        return super()._get_excluded_changed_fields() | {
            "last_ring_event_id",
            "last_smart_detect",
            "last_smart_detect_event_id",
            "talkback_stream",
        }

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        # LCD messages comes back as empty dict {}
        if "lcdMessage" in data and len(data["lcdMessage"].keys()) == 0:
            del data["lcdMessage"]

        return super().unifi_dict_to_dict(data)

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:

        if data is not None:
            if "motion_zones" in data:
                data["motion_zones"] = [MotionZone(**z).unifi_dict() for z in data["motion_zones"]]
            if "privacy_zones" in data:
                data["privacy_zones"] = [CameraZone(**z).unifi_dict() for z in data["privacy_zones"]]
            if "smart_detect_zones" in data:
                data["smart_detect_zones"] = [SmartMotionZone(**z).unifi_dict() for z in data["smart_detect_zones"]]

        data = super().unifi_dict(data=data, exclude=exclude)

        if "lastRingEventId" in data:
            del data["lastRingEventId"]
        if "lastSmartDetect" in data:
            del data["lastSmartDetect"]
        if "lastSmartDetectEventId" in data:
            del data["lastSmartDetectEventId"]
        if "talkbackStream" in data:
            del data["talkbackStream"]
        if "lcdMessage" in data and data["lcdMessage"] is None:
            data["lcdMessage"] = {}

        return data

    def get_changed(self) -> Dict[str, Any]:
        updated = super().get_changed()

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

    @property
    def last_ring_event(self) -> Optional[Event]:
        if self.last_ring_event_id is None:
            return None

        return self.api.bootstrap.events.get(self.last_ring_event_id)

    def update_from_dict(self, data: Dict[str, Any]) -> Camera:
        # a message in the past is actually a singal to wipe the message
        reset_at = data.get("lcd_message", {}).get("reset_at")
        if reset_at is not None:
            reset_at = from_js_time(reset_at)
            if utc_now() > reset_at:
                data["lcd_message"] = None

        return super().update_from_dict(data)

    @property
    def last_smart_detect_event(self) -> Optional[Event]:
        if self.last_smart_detect_event_id is None:
            return None

        return self.api.bootstrap.events.get(self.last_smart_detect_event_id)

    @property
    def timelapse_url(self) -> str:
        return f"{self.api.base_url}/protect/timelapse/{self.id}"

    @property
    def is_privacy_on(self) -> bool:
        index, _ = self.get_privacy_zone()
        return index is not None

    def get_privacy_zone(self) -> Tuple[Optional[int], Optional[CameraZone]]:
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

    async def get_snapshot(self, width: Optional[int] = None, height: Optional[int] = None) -> Optional[bytes]:
        """Gets snapshot for camera"""

        return await self.api.get_camera_snapshot(self.id, width, height)

    async def get_video(self, start: datetime, end: datetime, channel_index: int = 0) -> Optional[bytes]:
        """Gets video clip for camera at a given time"""

        return await self.api.get_camera_video(self.id, start, end, channel_index)

    async def set_recording_mode(self, mode: RecordingMode) -> None:
        """Sets recording mode on camera"""

        self.recording_settings.mode = mode
        await self.save_device()

    async def set_ir_led_model(self, mode: IRLEDMode) -> None:
        """Sets IR LED mode on camera"""

        if not self.feature_flags.has_led_ir:
            raise BadRequest("Camera does not have an LED IR")

        self.isp_settings.ir_led_mode = mode
        await self.save_device()

    async def set_status_light(self, enabled: bool) -> None:
        """Sets status indicicator light on camera"""

        if not self.feature_flags.has_led_status:
            raise BadRequest("Camera does not have status light")

        self.led_settings.is_enabled = enabled
        self.led_settings.blink_rate = 0
        await self.save_device()

    async def set_hdr(self, enabled: bool) -> None:
        """Sets HDR (High Dynamic Range) on camera"""

        if not self.feature_flags.has_hdr:
            raise BadRequest("Camera does not have HDR")

        self.hdr_mode = enabled
        await self.save_device()

    async def set_video_mode(self, mode: VideoMode) -> None:
        """Sets video mode on camera"""

        if mode not in self.feature_flags.video_modes:
            raise BadRequest(f"Camera does not have {mode}")

        self.video_mode = mode
        await self.save_device()

    async def set_camera_zoom(self, level: int) -> None:
        """Sets zoom level for camera"""

        if not self.feature_flags.can_optical_zoom:
            raise BadRequest("Camera cannot optical zoom")

        self.isp_settings.zoom_position = PercentInt(level)
        await self.save_device()

    async def set_wdr_level(self, level: int) -> None:
        """Sets WDR (Wide Dynamic Range) on camera"""

        if self.feature_flags.has_hdr:
            raise BadRequest("Cannot set WDR on cameras with HDR")

        self.isp_settings.wdr = WDRLevel(level)
        await self.save_device()

    async def set_mic_volume(self, level: int) -> None:
        """Sets the mic sensitivity level on camera"""

        if not self.feature_flags.has_mic:
            raise BadRequest("Camera does not have mic")

        self.mic_volume = PercentInt(level)
        await self.save_device()

    async def set_speaker_volume(self, level: int) -> None:
        """Sets the speaker sensitivity level on camera"""

        if not self.feature_flags.has_speaker:
            raise BadRequest("Camera does not have speaker")

        self.speaker_settings.volume = PercentInt(level)
        await self.save_device()

    async def set_chime_duration(self, duration: int) -> None:
        """Sets chime duration for doorbell. Requires camera to be a doorbell"""

        if not self.feature_flags.has_chime:
            raise BadRequest("Camera does not have a chime")

        self.chime_duration = ChimeDuration(duration)
        await self.save_device()

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
            self.lcd_message = None
            # UniFi Protect bug: clearing LCD text message does _not_ emit a WS message
            await self.save_device(force_emit=True)
            return

        if text_type != DoorbellMessageType.CUSTOM_MESSAGE:
            if text is not None:
                raise BadRequest("Can only set text if text_type is CUSTOM_MESSAGE")
            text = text_type.value.replace("_", " ")

        if reset_at == DEFAULT:
            reset_at = utc_now() + self.api.bootstrap.nvr.doorbell_settings.default_message_reset_timeout

        self.lcd_message = LCDMessage(api=self._api, type=text_type, text=text, reset_at=reset_at)
        await self.save_device()

    async def set_privacy(
        self, enabled: bool, mic_level: Optional[int] = None, recording_mode: Optional[RecordingMode] = None
    ) -> None:
        """Adds/removes a privacy zone that blacks out the whole camera"""

        if not self.feature_flags.has_privacy_mask:
            raise BadRequest("Camera does not allow privacy zones")

        if enabled:
            self.add_privacy_zone()
        else:
            self.remove_privacy_zone()

        if mic_level is not None:
            self.mic_volume = PercentInt(mic_level)

        if recording_mode is not None:
            self.recording_settings.mode = recording_mode

        await self.save_device()

    def create_talkback_stream(self, content_url: str, ffmpeg_path: Optional[Path] = None) -> TalkbackStream:
        """
        Creates a subprocess to play audio to a camera through its speaker.

        Requires ffmpeg to use.

        Args:

        * `content_url`: Either a URL accessible by python or a path to a file (ffmepg's `-i` parameter)
        * `ffmpeg_path`: Optional path to ffmpeg binary

        Use either `await stream.run_until_complete()` or `await stream.start()` to start subprocess command
        after getting the stream.

        `.play_audio()` is a helper that wraps this method and automatically runs the subprocess as well
        """

        if self.talkback_stream is not None and self.talkback_stream.is_running:
            raise BadRequest("Camera is already playing audio")

        self.talkback_stream = TalkbackStream(self, content_url, ffmpeg_path)
        return self.talkback_stream

    async def play_audio(self, content_url: str, ffmpeg_path: Optional[Path] = None) -> None:
        """
        Plays audio to a camera through its speaker.

        Requires ffmpeg to use.

        Args:

        * `content_url`: Either a URL accessible by python or a path to a file (ffmepg's `-i` parameter)
        * `ffmpeg_path`: Optional path to ffmpeg binary
        """

        stream = self.create_talkback_stream(content_url, ffmpeg_path)

        await stream.run_until_complete()

        _LOGGER.debug("ffmpeg stdout:\n%s", "\n".join(stream.stdout))
        _LOGGER.debug("ffmpeg stderr:\n%s", "\n".join(stream.stderr))
        if stream.is_error:
            error = "\n".join(stream.stderr)
            raise StreamError("Error while playing audio (ffmpeg): \n" + error)


class Viewer(ProtectAdoptableDeviceModel):
    stream_limit: int
    software_version: str
    liveview_id: str

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {**super()._get_unifi_remaps(), "liveview": "liveviewId"}

    @property
    def liveview(self) -> Optional[Liveview]:
        # user may not have permission to see the liveview
        return self.api.bootstrap.liveviews.get(self.liveview_id)

    async def set_liveview(self, liveview: Liveview) -> None:
        """
        Sets the liveview current set for the viewer

        Args:

        * `liveview`: The liveview you want to set
        """

        if self._api is not None:
            if liveview.id not in self._api.bootstrap.liveviews:
                raise BadRequest("Unknown liveview")

        self.liveview_id = liveview.id
        # UniFi Protect bug: changing the liveview does _not_ emit a WS message
        await self.save_device(force_emit=True)


class Bridge(ProtectAdoptableDeviceModel):
    platform: str


class SensorSettingsBase(ProtectBaseObject):
    is_enabled: bool


class SensorThresholdSettings(SensorSettingsBase):
    margin: float
    # "safe" thresholds for alerting
    # anything below/above will trigger alert
    low_threshold: Optional[float]
    high_threshold: Optional[float]


class SensorSensitivitySettings(SensorSettingsBase):
    sensitivity: PercentInt


class SensorBatteryStatus(ProtectBaseObject):
    percentage: PercentInt
    is_low: bool


class SensorStat(ProtectBaseObject):
    value: Optional[float]
    status: str


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

    # TODO:
    # mountType

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {**super()._get_unifi_remaps(), "camera": "cameraId"}

    @property
    def camera(self) -> Optional[Camera]:
        """Paired Camera will always be none if no camera is paired"""

        if self.camera_id is None:
            return None

        return self.api.bootstrap.cameras[self.camera_id]
