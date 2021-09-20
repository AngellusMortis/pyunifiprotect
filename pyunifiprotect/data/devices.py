"""Unifi Protect Data."""
from __future__ import annotations

from datetime import datetime, timedelta
from ipaddress import IPv4Address
from typing import TYPE_CHECKING, List, Optional, Tuple
from uuid import UUID

from pydantic.color import Color

from ..exceptions import NvrError
from ..utils import process_datetime, serialize_point, to_js_time, to_ms, to_s
from .base import (
    ProtectAdoptableDeviceModel,
    ProtectBaseObject,
    ProtectMotionDeviceModel,
)
from .types import (
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

if TYPE_CHECKING:
    from .nvr import Liveview


class LightDeviceSettings(ProtectBaseObject):
    # Status LED
    is_indicator_enabled: bool
    # Brightness
    led_level: LEDLevel
    # unknown
    lux_sensitivity: str
    pir_duration: timedelta
    pir_sensitivity: PercentInt

    def __init__(self, **kwargs):
        kwargs["pir_duration"] = timedelta(milliseconds=kwargs.pop("pirDuration"))

        super().__init__(**kwargs)

    def unifi_dict(self):
        data = super().unifi_dict()
        data["pirDuration"] = to_ms(self.pir_duration)
        return data


class LightOnSettings(ProtectBaseObject):
    # Manual toggle in UI
    is_led_force_on: bool


class LightModeSettings(ProtectBaseObject):
    # main "Lighting" settings
    mode: LightModeType
    enable_at: LightModeEnableType

    def unifi_dict(self):
        data = super().unifi_dict()
        data["mode"] = data["mode"].value
        data["enableAt"] = data["enableAt"].value
        return data


class Light(ProtectMotionDeviceModel):
    is_pir_motion_detected: bool
    is_light_on: bool
    is_locating: bool
    light_device_settings: LightDeviceSettings
    light_on_settings: LightOnSettings
    light_mode_settings: LightModeSettings
    camera_id: Optional[str]
    is_camera_paired: bool

    def __init__(self, **kwargs):
        kwargs["camera_id"] = kwargs.pop("camera")

        super().__init__(**kwargs)

    def unifi_dict(self):
        data = super().unifi_dict()
        data["camera"] = data.pop("cameraId")
        data["lightDeviceSettings"] = self.light_device_settings.unifi_dict()
        return data

    @property
    def camera(self) -> Optional[Camera]:
        """Paired Camera will always be none if no camera is paired"""

        if self.camera_id is None:
            return None

        if self._api is None:
            raise NvrError("API Client not initialized")

        return self._api.bootstrap.cameras[self.camera_id]


class EventStats(ProtectBaseObject):
    today: int
    average: int
    last_days: List[int]
    recent_hours: List[int] = []

    def unifi_dict(self):
        data = super().unifi_dict()
        if len(data["recentHours"]) == 0:
            del data["recentHours"]

        return data


class CameraEventStats(ProtectBaseObject):
    motion: EventStats
    smart: EventStats

    def unifi_dict(self):
        return {"motion": self.motion.unifi_dict(), "smart": self.smart.unifi_dict()}


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

    def __init__(self, **kwargs):
        kwargs["pre_padding"] = timedelta(seconds=kwargs.pop("prePaddingSecs"))
        kwargs["post_padding"] = timedelta(seconds=kwargs.pop("postPaddingSecs"))
        kwargs["min_motion_event_trigger"] = timedelta(seconds=kwargs.pop("minMotionEventTrigger"))
        kwargs["end_motion_event_delay"] = timedelta(seconds=kwargs.pop("endMotionEventDelay"))

        super().__init__(**kwargs)

    def unifi_dict(self):
        data = super().unifi_dict()
        data["prePaddingSecs"] = to_s(data.pop("prePadding"))
        data["postPaddingSecs"] = to_s(data.pop("postPadding"))
        data["minMotionEventTrigger"] = to_s(data.pop("minMotionEventTrigger"))
        data["endMotionEventDelay"] = to_s(data.pop("endMotionEventDelay"))
        data["mode"] = data["mode"].value

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

    def __init__(self, **kwargs):
        kwargs["resetAt"] = process_datetime(kwargs, "resetAt")

        super().__init__(**kwargs)

        self._fix_text()

    def _fix_text(self):
        if self.type != DoorbellMessageType.CUSTOM_MESSAGE:
            self.text = self.type.value.replace("_", " ")

    def unifi_dict(self):
        self._fix_text()

        data = super().unifi_dict()
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

    def unifi_dict(self):
        data = super().unifi_dict()
        data["bindAddr"] = str(data["bindAddr"])

        return data


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

    def __init__(self, **kwargs):
        kwargs["recordingStart"] = process_datetime(kwargs, "recordingStart")
        kwargs["recordingEnd"] = process_datetime(kwargs, "recordingEnd")
        kwargs["recordingStartLQ"] = process_datetime(kwargs, "recordingStartLQ")
        kwargs["recordingEndLQ"] = process_datetime(kwargs, "recordingEndLQ")
        kwargs["timelapseStart"] = process_datetime(kwargs, "timelapseStart")
        kwargs["timelapseEnd"] = process_datetime(kwargs, "timelapseEnd")
        kwargs["timelapseStartLQ"] = process_datetime(kwargs, "timelapseStartLQ")
        kwargs["timelapseEndLQ"] = process_datetime(kwargs, "timelapseEndLQ")

        super().__init__(**kwargs)

    def unifi_dict(self):
        data = super().unifi_dict()
        data["recordingStart"] = to_js_time(data["recordingStart"])
        data["recordingEnd"] = to_js_time(data["recordingEnd"])
        data["recordingStartLQ"] = to_js_time(data.pop("recordingStartLq"))
        data["recordingEndLQ"] = to_js_time(data.pop("recordingEndLq"))
        data["timelapseStart"] = to_js_time(data["timelapseStart"])
        data["timelapseEnd"] = to_js_time(data["timelapseEnd"])
        data["timelapseStartLQ"] = to_js_time(data.pop("timelapseStartLq"))
        data["timelapseEndLQ"] = to_js_time(data.pop("timelapseEndLq"))

        return data


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

    def __init__(self, **kwargs):
        if kwargs["storage"] == {}:
            del kwargs["storage"]

        super().__init__(**kwargs)

    def unifi_dict(self):
        data = super().unifi_dict()
        data["wifi"] = self.wifi.unifi_dict()
        data["battery"] = self.battery.unifi_dict()
        data["video"] = self.video.unifi_dict()

        if data["storage"] is None:
            data["storage"] = {}

        return data


class CameraZone(ProtectBaseObject):
    id: int
    name: str
    color: Color
    points: List[Tuple[Percent, Percent]]

    def unifi_dict(self):
        data = super().unifi_dict()
        data["color"] = self.color.as_hex().upper()
        data["points"] = [serialize_point(p) for p in self.points]

        return data


class MotionZone(CameraZone):
    sensitivity: PercentInt


class SmartMotionZone(MotionZone):
    object_types: List[SmartDetectObjectType]


class Camera(ProtectMotionDeviceModel):
    is_deleting: bool
    # Microphone Sensitivity
    mic_volume: PercentInt
    is_mic_enabled: bool
    is_recording: bool
    is_motion_detected: bool
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
    # motionZones
    # privacyZones
    # smartDetectZones
    # smartDetectLines
    # featureFlags

    def __init__(self, **kwargs):
        # LCD messages comes back as empty dict {}
        if "lcdMessage" in kwargs and len(kwargs["lcdMessage"].keys()) == 0:
            del kwargs["lcdMessage"]

        super().__init__(**kwargs)

    def unifi_dict(self):
        data = super().unifi_dict()
        data["videoMode"] = data["videoMode"].value
        data["lastRing"] = to_js_time(data["lastRing"])
        data["anonymousDeviceId"] = str(data["anonymousDeviceId"])
        data["recordingSettings"] = self.recording_settings.unifi_dict()
        data["eventStats"] = self.event_stats.unifi_dict()
        data["talkbackSettings"] = self.talkback_settings.unifi_dict()
        data["channels"] = [c.unifi_dict() for c in self.channels]
        data["stats"] = self.stats.unifi_dict()
        data["motionZones"] = [z.unifi_dict() for z in self.motion_zones]
        data["privacyZones"] = [z.unifi_dict() for z in self.privacy_zones]
        data["smartDetectZones"] = [z.unifi_dict() for z in self.smart_detect_zones]

        if self.lcd_message is None:
            data["lcdMessage"] = {}

        return data


class Viewer(ProtectAdoptableDeviceModel):
    stream_limit: int
    software_version: str
    liveview_id: str

    def __init__(self, **kwargs):
        kwargs["liveview_id"] = kwargs.pop("liveview")

        super().__init__(**kwargs)

    def unifi_dict(self):
        data = super().unifi_dict()
        data["liveview"] = data.pop("liveviewId")

        return data

    @property
    def liveview(self) -> Liveview:
        if self._api is None:
            raise NvrError("API Client not initialized")

        return self._api.bootstrap.liveviews[self.liveview_id]
