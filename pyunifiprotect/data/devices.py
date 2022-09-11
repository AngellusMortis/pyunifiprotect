"""UniFi Protect Data."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from ipaddress import IPv4Address
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple, Union
from uuid import UUID

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
    AutoExposureMode,
    ChimeType,
    Color,
    DoorbellMessageType,
    FocusMode,
    GeofencingSetting,
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
    SensorStatusType,
    SleepStateType,
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

    @classmethod
    def _get_read_only_fields(cls) -> Set[str]:
        return super()._get_read_only_fields() | {"isPirMotionDetected", "isLightOn", "isLocating"}

    @property
    def camera(self) -> Optional[Camera]:
        """Paired Camera will always be none if no camera is paired"""

        if self.camera_id is None:
            return None

        return self.api.bootstrap.cameras[self.camera_id]

    async def set_paired_camera(self, camera: Optional[Camera]) -> None:
        """Sets the camera paired with the light"""

        async with self._update_lock:
            if camera is None:
                self.camera_id = None
            else:
                self.camera_id = camera.id
            await self.save_device(force_emit=True)

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
            mode: Light trigger mode
            enable_at: Then the light automatically turns on by itself
            duration: How long the light should remain on after motion, must be timedelta between 15s and 900s
            sensitivity: PIR Motion sensitivity
        """

        if duration is not None and (duration.total_seconds() < 15 or duration.total_seconds() > 900):
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
        else:
            recent = data["recent_hours"]
            if len(recent) == 1 and recent[0] is None:
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
    fps_values: List[int]  # read only
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

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
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
    audio_types: Optional[List[SmartDetectAudioType]] = None

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "objectTypes" in data:
            data["objectTypes"] = convert_smart_types(data.pop("objectTypes"))
        if "audioTypes" in data:
            data["audioTypes"] = convert_smart_audio_types(data.pop("audioTypes"))

        return super().unifi_dict_to_dict(data)


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


class BatteryStats(ProtectBaseObject):
    percentage: Optional[PercentInt]
    is_charging: bool
    sleep_state: SleepStateType


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
    used: Optional[int]  # bytes
    rate: Optional[float]  # bytes / millisecond

    @property
    def rate_per_second(self) -> Optional[float]:
        if self.rate is None:
            return None

        return self.rate * 1000

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
        if "points" in data and isinstance(data["points"], Iterable):
            data["points"] = [(p[0], p[1]) for p in data["points"]]

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

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "objectTypes" in data:
            data["objectTypes"] = convert_smart_types(data.pop("objectTypes"))

        return super().unifi_dict_to_dict(data)


class PrivacyMaskCapability(ProtectBaseObject):
    max_masks: Optional[int]
    rectangle_only: bool


class Hotplug(ProtectBaseObject):
    audio: Optional[bool] = None
    video: Optional[bool] = None


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
    motion_algorithms: List[MotionAlgorithm]
    has_square_event_thumbnail: bool
    has_package_camera: bool
    privacy_mask_capability: PrivacyMaskCapability
    has_smart_detect: bool
    audio: List[str] = []
    audio_codecs: List[AudioCodecs] = []
    mount_positions: List[MountPosition] = []
    has_infrared: Optional[bool] = None
    lens_type: Optional[LensType] = None
    hotplug: Optional[Hotplug] = None

    # TODO:
    # focus
    # pan
    # tilt
    # zoom

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "smartDetectTypes" in data:
            data["smartDetectTypes"] = convert_smart_types(data.pop("smartDetectTypes"))
        if "videoModes" in data:
            data["videoModes"] = convert_video_modes(data.pop("videoModes"))

        return super().unifi_dict_to_dict(data)

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
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


class Camera(ProtectMotionDeviceModel):
    is_deleting: bool
    # Microphone Sensitivity
    mic_volume: PercentInt
    is_mic_enabled: bool
    is_recording: bool
    is_motion_detected: bool
    is_smart_detected: bool
    phy_rate: Optional[int]
    hdr_mode: bool
    # Recording Quality -> High Frame
    video_mode: VideoMode
    is_probing_for_wifi: bool
    chime_duration: timedelta
    last_ring: Optional[datetime]
    is_live_heatmap_enabled: bool
    anonymous_device_id: Optional[UUID]
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
    lenses: List[CameraLenses]
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

    # TODO: used for adopting
    # apMac read only
    # apRssi read only
    # elementInfo read only

    # TODO:
    # lastPrivacyZonePositionId
    # recordingSchedule
    # smartDetectLines
    # streamSharing read only

    # not directly from UniFi
    last_ring_event_id: Optional[str] = None
    last_smart_detect: Optional[datetime] = None
    last_smart_detect_event_id: Optional[str] = None
    talkback_stream: Optional[TalkbackStream] = None
    _last_ring_timeout: Optional[datetime] = PrivateAttr(None)

    @classmethod
    def _get_excluded_changed_fields(cls) -> Set[str]:
        return super()._get_excluded_changed_fields() | {
            "last_ring_event_id",
            "last_smart_detect",
            "last_smart_detect_event_id",
            "talkback_stream",
        }

    @classmethod
    def _get_read_only_fields(cls) -> Set[str]:
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
            "anonymousDeviceId",
            "eventStats",
            "videoReconfigurationInProgress",
            "lenses",
            "isPoorNetwork",
            "featureFlags",
        }

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        # LCD messages comes back as empty dict {}
        if "lcdMessage" in data and len(data["lcdMessage"].keys()) == 0:
            del data["lcdMessage"]
        if "chimeDuration" in data and not isinstance(data["chimeDuration"], timedelta):
            data["chimeDuration"] = timedelta(milliseconds=data["chimeDuration"])

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

    def update_from_dict(self, data: Dict[str, Any]) -> Camera:
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

    @property
    def can_detect_person(self) -> bool:
        return SmartDetectObjectType.PERSON in self.feature_flags.smart_detect_types

    @property
    def is_person_detection_on(self) -> bool:
        return SmartDetectObjectType.PERSON in self.smart_detect_settings.object_types

    @property
    def can_detect_vehicle(self) -> bool:
        return SmartDetectObjectType.VEHICLE in self.feature_flags.smart_detect_types

    @property
    def is_vehicle_detection_on(self) -> bool:
        return SmartDetectObjectType.VEHICLE in self.smart_detect_settings.object_types

    @property
    def can_detect_face(self) -> bool:
        return SmartDetectObjectType.FACE in self.feature_flags.smart_detect_types

    @property
    def is_face_detection_on(self) -> bool:
        return SmartDetectObjectType.FACE in self.smart_detect_settings.object_types

    @property
    def can_detect_pet(self) -> bool:
        return SmartDetectObjectType.PET in self.feature_flags.smart_detect_types

    @property
    def is_pet_detection_on(self) -> bool:
        return SmartDetectObjectType.PET in self.smart_detect_settings.object_types

    @property
    def can_detect_license_plate(self) -> bool:
        return SmartDetectObjectType.LICENSE_PLATE in self.feature_flags.smart_detect_types

    @property
    def is_license_plate_detection_on(self) -> bool:
        return SmartDetectObjectType.LICENSE_PLATE in self.smart_detect_settings.object_types

    @property
    def can_detect_package(self) -> bool:
        return SmartDetectObjectType.PACKAGE in self.feature_flags.smart_detect_types

    @property
    def is_package_detection_on(self) -> bool:
        return SmartDetectObjectType.PACKAGE in self.smart_detect_settings.object_types

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
        if len(self.channels) == 3:
            return self.channels[0]
        return None

    @property
    def medium_camera_channel(self) -> Optional[CameraChannel]:
        if len(self.channels) == 3:
            return self.channels[1]
        return None

    @property
    def low_camera_channel(self) -> Optional[CameraChannel]:
        if len(self.channels) == 3:
            return self.channels[2]
        return None

    @property
    def default_camera_channel(self) -> Optional[CameraChannel]:
        for channel in [self.high_camera_channel, self.medium_camera_channel, self.low_camera_channel]:
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
        return self.feature_flags.lens_type is None or self.feature_flags.lens_type != LensType.NONE

    @property
    def has_removable_lens(self) -> bool:
        return self.feature_flags.lens_type is not None

    @property
    def has_removable_speaker(self) -> bool:
        return self.feature_flags.hotplug is not None

    @property
    def has_mic(self) -> bool:
        return self.feature_flags.has_mic or self.has_removable_speaker

    def set_ring_timeout(self) -> None:
        self._last_ring_timeout = utc_now() + EVENT_PING_INTERVAL
        self._event_callback_ping()

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

    async def get_snapshot(
        self, width: Optional[int] = None, height: Optional[int] = None, dt: Optional[datetime] = None
    ) -> Optional[bytes]:
        """
        Gets snapshot for camera.

        Datetime of screenshot is approximate. It may be +/- a few seconds.
        """

        if not self.api.bootstrap.auth_user.can(ModelType.CAMERA, PermissionNode.READ_MEDIA, self):
            raise NotAuthorized(f"Do not have permission to read media for camera: {self.id}")

        return await self.api.get_camera_snapshot(self.id, width, height, dt=dt)

    async def get_package_snapshot(
        self,
        width: Optional[int] = None,
        height: Optional[int] = None,
        dt: Optional[datetime] = None,
    ) -> Optional[bytes]:
        """
        Gets snapshot from the package camera.

        Datetime of screenshot is approximate. It may be +/- a few seconds.
        """

        if not self.feature_flags.has_package_camera:
            raise BadRequest("Device does not have package camera")

        if not self.api.bootstrap.auth_user.can(ModelType.CAMERA, PermissionNode.READ_MEDIA, self):
            raise NotAuthorized(f"Do not have permission to read media for camera: {self.id}")

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
        """
        Exports MP4 video from a given camera at a specific time.

        Start/End of video export are approximate. It may be +/- a few seconds.

        It is recommended to provide a output file or progress callback for larger
        video clips, otherwise the full video must be downloaded to memory before
        being written.

        Providing the `fps` parameter creates a "timelapse" export wtih the given FPS
        value. Protect app gives the options for 60x (fps=4), 120x (fps=8), 300x
        (fps=20), and 600x (fps=40).
        """

        if not self.api.bootstrap.auth_user.can(ModelType.CAMERA, PermissionNode.READ_MEDIA, self):
            raise NotAuthorized(f"Do not have permission to read media for camera: {self.id}")

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

    async def set_motion_detection(self, enabled: bool) -> None:
        """Sets motion detection on camera"""

        def callback() -> None:
            self.recording_settings.enable_motion_detection = enabled

        await self.queue_update(callback)

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

        if not self.feature_flags.has_hdr:
            raise BadRequest("Camera does not have HDR")

        def callback() -> None:
            self.hdr_mode = enabled

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

    async def set_chime_duration(self, duration: timedelta | float | int) -> None:
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

    async def set_smart_detect_types(self, types: List[SmartDetectObjectType]) -> None:
        """Sets current enabled smart detection types. Requires camera to have smart detection"""

        if not self.feature_flags.has_smart_detect:
            raise BadRequest("Camera does not have a smart detections")

        def callback() -> None:
            self.smart_detect_settings.object_types = types

        await self.queue_update(callback)

    async def _set_object_detect(self, obj_to_mod: SmartDetectObjectType, enabled: bool) -> None:

        if obj_to_mod not in self.feature_flags.smart_detect_types:
            raise BadRequest(f"Camera does not support the {obj_to_mod} detection type")

        def callback() -> None:
            objects = self.smart_detect_settings.object_types
            if enabled:
                if obj_to_mod not in objects:
                    objects = objects + [obj_to_mod]
                    objects.sort()
            else:
                if obj_to_mod in objects:
                    objects.remove(obj_to_mod)
            self.smart_detect_settings.object_types = objects

        await self.queue_update(callback)

    async def set_person_detection(self, enabled: bool) -> None:
        """Toggles person smart detection. Requires camera to have smart detection"""

        return await self._set_object_detect(SmartDetectObjectType.PERSON, enabled)

    async def set_vehicle_detection(self, enabled: bool) -> None:
        """Toggles vehicle smart detection. Requires camera to have smart detection"""

        return await self._set_object_detect(SmartDetectObjectType.VEHICLE, enabled)

    async def set_face_detection(self, enabled: bool) -> None:
        """Toggles face smart detection. Requires camera to have smart detection"""

        return await self._set_object_detect(SmartDetectObjectType.FACE, enabled)

    async def set_pet_detection(self, enabled: bool) -> None:
        """Toggles pet smart detection. Requires camera to have smart detection"""

        return await self._set_object_detect(SmartDetectObjectType.PET, enabled)

    async def set_license_plate_detection(self, enabled: bool) -> None:
        """Toggles license plate smart detection. Requires camera to have smart detection"""

        return await self._set_object_detect(SmartDetectObjectType.LICENSE_PLATE, enabled)

    async def set_package_detection(self, enabled: bool) -> None:
        """Toggles package smart detection. Requires camera to have smart detection"""

        return await self._set_object_detect(SmartDetectObjectType.PACKAGE, enabled)

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

        def callback() -> None:
            self.lcd_message = LCDMessage(api=self._api, type=text_type, text=text, reset_at=reset_at)

        await self.queue_update(callback)

    async def set_privacy(
        self, enabled: bool, mic_level: Optional[int] = None, recording_mode: Optional[RecordingMode] = None
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

    def create_talkback_stream(self, content_url: str, ffmpeg_path: Optional[Path] = None) -> TalkbackStream:
        """
        Creates a subprocess to play audio to a camera through its speaker.

        Requires ffmpeg to use.

        Args:
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

    async def play_audio(self, content_url: str, ffmpeg_path: Optional[Path] = None, blocking: bool = True) -> None:
        """
        Plays audio to a camera through its speaker.

        Requires ffmpeg to use.

        Args:
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
    anonymous_device_id: Optional[UUID] = None

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {**super()._get_unifi_remaps(), "liveview": "liveviewId"}

    @classmethod
    def _get_read_only_fields(cls) -> Set[str]:
        return super()._get_read_only_fields() | {"softwareVersion"}

    @property
    def liveview(self) -> Optional[Liveview]:
        # user may not have permission to see the liveview
        return self.api.bootstrap.liveviews.get(self.liveview_id)

    async def set_liveview(self, liveview: Liveview) -> None:
        """
        Sets the liveview current set for the viewer

        Args:
            liveview: The liveview you want to set
        """

        if self._api is not None:
            if liveview.id not in self._api.bootstrap.liveviews:
                raise BadRequest("Unknown liveview")

        async with self._update_lock:
            self.liveview_id = liveview.id
            # UniFi Protect bug: changing the liveview does _not_ emit a WS message
            await self.save_device(force_emit=True)


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
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {**super()._get_unifi_remaps(), "camera": "cameraId"}

    @classmethod
    def _get_read_only_fields(cls) -> Set[str]:
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

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
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
        return self.mount_type in [MountType.DOOR, MountType.WINDOW, MountType.GARAGE]

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
        return self.mount_type != MountType.LEAK and self.temperature_settings.is_enabled

    @property
    def is_humidity_sensor_enabled(self) -> bool:
        return self.mount_type != MountType.LEAK and self.humidity_settings.is_enabled

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

        if not self.api.bootstrap.auth_user.can(ModelType.SENSOR, PermissionNode.WRITE, self):
            raise NotAuthorized(f"Do not have permission to clear tamper for sensor: {self.id}")
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
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {**super()._get_unifi_remaps(), "camera": "cameraId", "autoCloseTimeMs": "autoCloseTime"}

    @classmethod
    def _get_read_only_fields(cls) -> Set[str]:
        return super()._get_read_only_fields() | {"credentials", "lockStatus", "batteryStatus"}

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "autoCloseTimeMs" in data and not isinstance(data["autoCloseTimeMs"], timedelta):
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
        """
        Calibrate the doorlock.

        Door must be open and lock unlocked.
        """

        await self.api.calibrate_lock(self.id)


class Chime(ProtectAdoptableDeviceModel):
    volume: PercentInt
    is_probing_for_wifi: bool
    last_ring: Optional[datetime]
    is_wireless_uplink_enabled: bool
    camera_ids: List[str]

    # TODO: used for adoption
    # apMac  read only
    # apRssi  read only
    # elementInfo  read only

    @classmethod
    def _get_read_only_fields(cls) -> Set[str]:
        return super()._get_read_only_fields() | {"isProbingForWifi", "lastRing"}

    @property
    def cameras(self) -> List[Camera]:
        """Paired Cameras for chime"""

        if len(self.camera_ids) == 0:
            return []
        return [self.api.bootstrap.cameras[c] for c in self.camera_ids]

    async def set_volume(self, level: int) -> None:
        """Sets the volume on chime"""

        def callback() -> None:
            self.volume = PercentInt(level)

        await self.queue_update(callback)

    async def add_camera(self, camera: Camera) -> None:
        """Adds new paired camera to chime"""

        if not camera.feature_flags.has_chime:
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

    async def play(self) -> None:
        """Plays chime tone"""

        await self.api.play_speaker(self.id)

    async def play_buzzer(self) -> None:
        """Plays chime buzzer"""

        await self.api.play_buzzer(self.id)
