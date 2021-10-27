"""Unifi Protect Data."""
from __future__ import annotations

from datetime import datetime, timedelta
from ipaddress import IPv4Address
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Dict, List, Optional, Tuple
from uuid import UUID

from pydantic.color import Color

from pyunifiprotect.data.base import (
    ProtectAdoptableDeviceModel,
    ProtectBaseObject,
    ProtectMotionDeviceModel,
)
from pyunifiprotect.data.types import (
    DoorbellMessageType,
    LEDLevel,
    LightModeEnableType,
    LightModeType,
    Percent,
    PercentInt,
    RecordingMode,
    SmartDetectObjectType,
    VideoMode,
)
from pyunifiprotect.utils import process_datetime, serialize_point, to_js_time

if TYPE_CHECKING:
    from pyunifiprotect.data.nvr import Event, Liveview


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
    def clean_unifi_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "pirDuration" in data and not isinstance(data["pirDuration"], timedelta):
            data["pirDuration"] = timedelta(milliseconds=data["pirDuration"])

        return super().clean_unifi_dict(data)


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

    UNIFI_REMAP: ClassVar[Dict[str, str]] = {**ProtectMotionDeviceModel.UNIFI_REMAP, **{"camera": "cameraId"}}
    PROTECT_OBJ_FIELDS: ClassVar[Dict[str, Callable]] = {
        "lightDeviceSettings": LightDeviceSettings,
        "lightOnSettings": LightOnSettings,
        "lightModeSettings": LightModeSettings,
    }

    @property
    def camera(self) -> Optional[Camera]:
        """Paired Camera will always be none if no camera is paired"""

        if self.camera_id is None:
            return None

        return self.api.bootstrap.cameras[self.camera_id]


class EventStats(ProtectBaseObject):
    today: int
    average: int
    last_days: List[int]
    recent_hours: List[int] = []

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data)

        if "recentHours" in data and len(data["recentHours"]) == 0:
            del data["recentHours"]

        return data


class CameraEventStats(ProtectBaseObject):
    motion: EventStats
    smart: EventStats

    PROTECT_OBJ_FIELDS: ClassVar[Dict[str, Callable]] = {
        "motion": EventStats,
        "smart": EventStats,
    }


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


class ISPSettings(ProtectBaseObject):
    ae_mode: str
    ir_led_mode: str
    ir_led_level: int
    wdr: int
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
    zoom_position: int

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
    def clean_unifi_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "prePaddingSecs" in data:
            data["prePadding"] = timedelta(seconds=data.pop("prePaddingSecs"))
        if "postPaddingSecs" in data:
            data["postPadding"] = timedelta(seconds=data.pop("postPaddingSecs"))
        if "minMotionEventTrigger" in data and not isinstance(data["minMotionEventTrigger"], timedelta):
            data["minMotionEventTrigger"] = timedelta(seconds=data["minMotionEventTrigger"])
        if "endMotionEventDelay" in data and not isinstance(data["endMotionEventDelay"], timedelta):
            data["endMotionEventDelay"] = timedelta(seconds=data["endMotionEventDelay"])

        return super().clean_unifi_dict(data)

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data)

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
    def clean_unifi_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "resetAt" in data:
            data["resetAt"] = process_datetime(data, "resetAt")
        if "text" in data:
            data["text"] = cls._fix_text(data["text"], data.get("type"))

        return super().clean_unifi_dict(data)

    @classmethod
    def _fix_text(cls, text: str, text_type: Optional[str]) -> str:
        if text_type is None:
            text_type = cls.type.value

        if text_type != DoorbellMessageType.CUSTOM_MESSAGE.value:
            text = text_type.replace("_", " ")

        return text

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data)

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

    UNIFI_REMAP: ClassVar[Dict[str, str]] = {
        "recordingStartLQ": "recordingStartLq",
        "recordingEndLQ": "recordingEndLq",
        "timelapseStartLQ": "timelapseStartLq",
        "timelapseEndLQ": "timelapseEndLq",
    }

    @classmethod
    def clean_unifi_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
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

        return super().clean_unifi_dict(data)


class StorageStats(ProtectBaseObject):
    used: int
    rate: float


class CameraStats(ProtectBaseObject):
    rx_bytes: int
    tx_bytes: int
    wifi: WifiStats
    battery: BatteryStats
    video: VideoStats
    storage: Optional[StorageStats]
    wifi_quality: PercentInt
    wifi_strength: int

    PROTECT_OBJ_FIELDS: ClassVar[Dict[str, Callable]] = {
        "wifi": WifiStats,
        "battery": BatteryStats,
        "video": VideoStats,
        "storage": StorageStats,
    }

    @classmethod
    def clean_unifi_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "storage" in data and data["storage"] == {}:
            del data["storage"]

        return super().clean_unifi_dict(data)

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data)

        if "storage" in data and data["storage"] is None:
            data["storage"] = {}

        return data


class CameraZone(ProtectBaseObject):
    id: int
    name: str
    color: Color
    points: List[Tuple[Percent, Percent]]

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data)

        if "points" in data:
            data["points"] = [serialize_point(p) for p in data["points"]]

        return data


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

    UNIFI_REMAP: ClassVar[Dict[str, str]] = {"hasAutoICROnly": "hasAutoIcrOnly"}
    PROTECT_OBJ_FIELDS: ClassVar[Dict[str, Callable]] = {"privacyMaskCapability": PrivacyMaskCapability}


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
    chime_duration: int
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

    PROTECT_OBJ_FIELDS: ClassVar[Dict[str, Callable]] = {
        "eventStats": CameraEventStats,
        "ispSettings": ISPSettings,
        "talkbackSettings": TalkbackSettings,
        "osdSettings": OSDSettings,
        "ledSettings": LEDSettings,
        "speakerSettings": SpeakerSettings,
        "recordingSettings": RecordingSettings,
        "smartDetectSettings": SmartDetectSettings,
        "stats": CameraStats,
        "featureFlags": FeatureFlags,
        "pirSettings": PIRSettings,
        "lcdMessage": LCDMessage,
    }

    @classmethod
    def clean_unifi_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        # LCD messages comes back as empty dict {}
        if "lcdMessage" in data and len(data["lcdMessage"].keys()) == 0:
            del data["lcdMessage"]

        return super().clean_unifi_dict(data)

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if data is None:
            data = self.dict()
            data["motion_zones"] = [o.unifi_dict() for o in self.motion_zones]
            data["privacy_zones"] = [o.unifi_dict() for o in self.privacy_zones]
            data["smart_detect_zones"] = [o.unifi_dict() for o in self.smart_detect_zones]

        data = super().unifi_dict(data=data)

        if "lastRingEventId" in data:
            del data["lastRingEventId"]
        if "lastSmartDetect" in data:
            del data["lastSmartDetect"]
        if "lastSmartDetectEventId" in data:
            del data["lastSmartDetectEventId"]
        if "lcdMessage" in data and data["lcdMessage"] is None:
            data["lcdMessage"] = {}

        return data

    @property
    def last_ring_event(self) -> Optional[Event]:
        if self.last_ring_event_id is None:
            return None

        return self.api.bootstrap.events.get(self.last_ring_event_id)

    @property
    def last_smart_detect_event(self) -> Optional[Event]:
        if self.last_smart_detect_event_id is None:
            return None

        return self.api.bootstrap.events.get(self.last_smart_detect_event_id)


class Viewer(ProtectAdoptableDeviceModel):
    stream_limit: int
    software_version: str
    liveview_id: str

    UNIFI_REMAP: ClassVar[Dict[str, str]] = {**ProtectAdoptableDeviceModel.UNIFI_REMAP, **{"liveview": "liveviewId"}}

    @property
    def liveview(self) -> Liveview:
        return self.api.bootstrap.liveviews[self.liveview_id]


class Bridge(ProtectAdoptableDeviceModel):
    hardware_revision: int
    platform: str
