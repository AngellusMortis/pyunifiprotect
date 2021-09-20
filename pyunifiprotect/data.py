"""Unifi Protect Data."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, tzinfo
import enum
from ipaddress import IPv4Address
import json
from pathlib import Path
import struct
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Type
from uuid import UUID
import zlib

from pydantic import BaseModel
from pydantic.fields import PrivateAttr
import pytz

from .exceptions import DataDecodeError, NvrError, WSDecodeError
from .utils import (
    process_datetime,
    to_camel_case_dict,
    to_js_time,
    to_ms,
    to_s,
    to_snake_case,
)

if TYPE_CHECKING:
    from .unifi_protect_server import ProtectApiClient

WS_HEADER_SIZE = 8
SUPPORTED_PROTECT_MODELS = ["cameras", "users", "groups", "liveviews", "viewers", "lights"]


@enum.unique
class ModelType(str, enum.Enum):
    CAMERA = "camera"
    CLOUD_IDENTITY = "cloudIdentity"
    EVENT = "event"
    GROUP = "group"
    LIGHT = "light"
    LIVEVIEW = "liveview"
    NVR = "nvr"
    USER = "user"
    USER_LOCATION = "userLocation"
    VIEWPORT = "viewer"
    DISPLAYS = "display"
    BRIDGE = "bridge"
    SENSOR = "sensor"
    DOORLOCK = "doorlock"


@enum.unique
class EventType(str, enum.Enum):
    SMART_DETECT = "smartDetectZone"
    MOTION = "motion"
    RING = "ring"
    DISCONNECT = "disconnect"
    PROVISION = "provision"
    ACCESS = "access"
    OFFLINE = "offline"
    OFF = "off"


@enum.unique
class StateType(str, enum.Enum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"


@enum.unique
class ProtectWSPayloadFormat(int, enum.Enum):
    """Websocket Payload formats."""

    JSON = 1
    UTF8String = 2
    NodeBuffer = 3


@enum.unique
class SmartDetectObjectType(str, enum.Enum):
    PERSON = "person"
    VEHICLE = "vehicle"


@enum.unique
class DoorbellMessageType(str, enum.Enum):
    LEAVE_PACKAGE_AT_DOOR = "LEAVE_PACKAGE_AT_DOOR"
    DO_NOT_DISTURB = "DO_NOT_DISTURB"


class WSPacketFrameHeader(BaseModel):
    packet_type: int
    payload_format: int
    deflated: int
    unknown: int
    payload_size: int


class WSRawPacketFrame:
    data: bytes = b""
    position: int = 0
    header: Optional[WSPacketFrameHeader] = None
    payload_format: ProtectWSPayloadFormat = ProtectWSPayloadFormat.NodeBuffer
    is_deflated: bool = False
    length: int = 0

    def set_data_from_binary(self, data: bytes):
        self.data = data
        if self.header is not None and self.header.deflated:
            self.data = zlib.decompress(self.data)

    def get_binary_from_data(self) -> bytes:
        data = self.data
        if self.is_deflated:
            data = zlib.compress(data)

        return data

    @staticmethod
    def klass_from_format(format_raw=bytes):
        payload_format = ProtectWSPayloadFormat(format_raw)

        if payload_format == ProtectWSPayloadFormat.JSON:
            return WSJSONPacketFrame

        return WSRawPacketFrame

    @staticmethod
    def from_binary(data: bytes, position: int = 0, klass: Optional[Type[WSRawPacketFrame]] = None) -> WSRawPacketFrame:
        """Decode a unifi updates websocket frame."""
        # The format of the frame is
        # b: packet_type
        # b: payload_format
        # b: deflated
        # b: unknown
        # i: payload_size

        header_end = position + WS_HEADER_SIZE

        try:
            packet_type, payload_format, deflated, unknown, payload_size = struct.unpack(
                "!bbbbi", data[position:header_end]
            )
        except struct.error as e:
            raise WSDecodeError from e

        if klass is None:
            frame = WSRawPacketFrame.klass_from_format(payload_format)()
        else:
            frame = klass()
            frame.payload_format = ProtectWSPayloadFormat(payload_format)

        frame.header = WSPacketFrameHeader(
            packet_type=packet_type,
            payload_format=payload_format,
            deflated=deflated,
            unknown=unknown,
            payload_size=payload_size,
        )
        frame.length = WS_HEADER_SIZE + frame.header.payload_size
        frame.is_deflated = bool(frame.header.deflated)
        frame_end = header_end + frame.header.payload_size
        frame.set_data_from_binary(data[header_end:frame_end])

        return frame

    @property
    def packed(self):
        data = self.get_binary_from_data()
        header = struct.pack(
            "!bbbbi",
            self.header.packet_type,
            self.header.payload_format,
            self.header.deflated,
            self.header.unknown,
            len(data),
        )

        return header + data


class WSJSONPacketFrame(WSRawPacketFrame):
    data: dict = {}  # type: ignore
    payload_format: ProtectWSPayloadFormat = ProtectWSPayloadFormat.NodeBuffer

    def set_data_from_binary(self, data: bytes):
        if self.header is not None and self.header.deflated:
            data = zlib.decompress(data)

        self.data = json.loads(data)

    def get_binary_from_data(self) -> bytes:
        data = self.json.encode("utf-8")
        if self.is_deflated:
            data = zlib.compress(data)

        return data

    @property
    def json(self) -> str:
        return json.dumps(self.data)


class WSPacket:
    _raw: bytes
    _raw_encoded: Optional[str] = None

    _action_frame: Optional[WSRawPacketFrame] = None
    _data_frame: Optional[WSRawPacketFrame] = None

    def __init__(self, data: bytes):
        self._raw = data

    def decode(self):
        self._action_frame = WSRawPacketFrame.from_binary(self._raw)
        self._data_frame = WSRawPacketFrame.from_binary(self._raw, self._action_frame.length)

    @property
    def action_frame(self) -> WSRawPacketFrame:
        if self._action_frame is None:
            self.decode()

        if self._action_frame is None:
            raise WSDecodeError("Packet unexpectedly not decoded")

        return self._action_frame

    @property
    def data_frame(self) -> WSRawPacketFrame:
        if self._data_frame is None:
            self.decode()

        if self._data_frame is None:
            raise WSDecodeError("Packet unexpectedly not decoded")

        return self._data_frame

    @property
    def raw(self) -> bytes:
        return self._raw

    @raw.setter
    def raw(self, data: bytes):
        self._raw = data
        self._action_frame = None
        self._data_frame = None
        self._raw_encoded = None

    @property
    def raw_base64(self) -> str:
        if self._raw_encoded is None:
            self._raw_encoded = base64.b64encode(self._raw).decode("utf-8")

        return self._raw_encoded

    def pack_frames(self) -> bytes:
        self._raw_encoded = None
        self._raw = self.action_frame.packed + self.data_frame.packed

        return self._raw


class ProtectBaseObject(BaseModel):
    _api: Optional[ProtectApiClient] = PrivateAttr(None)

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, api=None, **data: Any) -> None:
        for key in list(data.keys()):
            data[to_snake_case(key)] = data.pop(key)

        super().__init__(**data)

        self._api = api

    def unifi_dict(self):
        data = to_camel_case_dict(self.dict())

        return data


class ProtectModel(ProtectBaseObject):
    model: Optional[ModelType]

    def __init__(self, **kwargs):
        model_key = kwargs.pop("modelKey", None)
        if model_key is not None:
            kwargs["model"] = ModelType(model_key)

        super().__init__(**kwargs)

    @staticmethod
    def klass_from_dict(data: Dict[str, Any]) -> Type[ProtectModel]:
        if "modelKey" not in data:
            raise DataDecodeError("No modelKey")

        model = ModelType(data["modelKey"])

        klass: Optional[Type[ProtectModel]] = None

        if model == ModelType.EVENT:
            klass = Event
        elif model == ModelType.GROUP:
            klass = Group
        elif model == ModelType.USER_LOCATION:
            klass = UserLocation
        elif model == ModelType.CLOUD_IDENTITY:
            klass = CloudAccount
        elif model == ModelType.USER:
            klass = User
        elif model == ModelType.NVR:
            klass = NVR
        elif model == ModelType.LIGHT:
            klass = Light
        elif model == ModelType.CAMERA:
            klass = Camera
        elif model == ModelType.LIVEVIEW:
            klass = Liveview
        elif model == ModelType.VIEWPORT:
            klass = Viewer

        if klass is None:
            raise DataDecodeError("Unknown modelKey")

        return klass

    @staticmethod
    def from_unifi_dict(
        data: Dict[str, Any], api: Optional[ProtectApiClient] = None, klass: Optional[Type[ProtectModel]] = None
    ) -> ProtectModel:
        if "modelKey" not in data:
            raise DataDecodeError("No modelKey")

        if klass is None:
            klass = ProtectModel.klass_from_dict(data)

        return klass(**data, api=api)

    def unifi_dict(self):
        data = super().unifi_dict()

        if data["model"] is None:
            del data["model"]
        else:
            data["modelKey"] = data.pop("model").value

        return data


class ProtectModelWithId(ProtectModel):
    id: str


class ProtectDeviceModel(ProtectModelWithId):
    name: str
    type: str
    mac: str
    host: IPv4Address
    up_since: Optional[datetime]
    uptime: Optional[timedelta]
    last_seen: datetime
    hardware_revision: Optional[str]
    firmware_version: str
    is_updating: bool
    is_ssh_enabled: bool

    def __init__(self, **kwargs):
        kwargs["lastSeen"] = process_datetime(kwargs, "lastSeen")

        if kwargs["upSince"] is not None:
            kwargs["upSince"] = process_datetime(kwargs, "upSince")

        if kwargs["uptime"] is not None:
            kwargs["uptime"] = timedelta(milliseconds=kwargs["uptime"])

        super().__init__(**kwargs)

    def unifi_dict(self):
        data = super().unifi_dict()
        data["lastSeen"] = to_js_time(data["lastSeen"])
        data["upSince"] = to_js_time(data["upSince"])
        data["host"] = str(data["host"])
        data["uptime"] = to_ms(data["uptime"])

        return data


class WiredConnectionState(ProtectBaseObject):
    phy_rate: Optional[int]


class WifiConnectionState(WiredConnectionState):
    channel: Optional[int]
    frequency: Optional[int]
    signal_quality: Optional[int]
    signal_strength: Optional[int]


class ProtectAdoptableDeviceModel(ProtectDeviceModel):
    state: StateType
    connection_host: IPv4Address
    connected_since: Optional[datetime]
    latest_firmware_version: str
    firmware_build: str
    is_adopting: bool
    is_adopted: bool
    is_adopted_by_other: bool
    is_provisioned: bool
    is_rebooting: bool
    can_adopt: bool
    is_attempting_to_connect: bool
    is_connected: bool

    wired_connection_state: Optional[WiredConnectionState] = None
    wifi_connection_state: Optional[WifiConnectionState] = None

    def unifi_dict(self):
        data = super().unifi_dict()
        data["connectionHost"] = str(data["connectionHost"])
        data["connectedSince"] = to_js_time(data["connectedSince"])

        if data["wiredConnectionState"] is None:
            del data["wiredConnectionState"]

        if data["wifiConnectionState"] is None:
            del data["wifiConnectionState"]

        return data


class ProtectMotionDeviceModel(ProtectAdoptableDeviceModel):
    last_motion: Optional[datetime]
    is_dark: bool

    def __init__(self, **kwargs):
        kwargs["lastMotion"] = process_datetime(kwargs, "lastMotion")

        super().__init__(**kwargs)

    def unifi_dict(self):
        data = super().unifi_dict()
        data["lastMotion"] = to_js_time(data["lastMotion"])

        return data


class Event(ProtectModelWithId):
    type: EventType
    start: datetime
    end: Optional[datetime]
    score: int
    heatmap_id: Optional[str]
    camera_id: Optional[str]
    smart_detect_types: List[SmartDetectObjectType]
    smart_detect_events_ids: List[str]
    thumbnail_id: Optional[str]
    user_id: Optional[str]

    # TODO:
    # metadata
    # partition

    def __init__(self, **kwargs):
        kwargs["type"] = EventType(kwargs["type"])
        kwargs["start"] = process_datetime(kwargs, "start")
        kwargs["end"] = process_datetime(kwargs, "end")
        kwargs["heatmap_id"] = kwargs.pop("heatmap")
        kwargs["camera_id"] = kwargs.pop("camera")
        kwargs["smart_detect_events_ids"] = kwargs.pop("smartDetectEvents")
        kwargs["thumbnail_id"] = kwargs.pop("thumbnail")
        kwargs["user_id"] = kwargs.pop("user")

        super().__init__(**kwargs)

    def unifi_dict(self):
        data = super().unifi_dict()
        data["type"] = data["type"].value
        data["start"] = to_js_time(data["start"])
        data["end"] = to_js_time(data["end"])
        data["heatmap"] = data.pop("heatmapId")
        data["camera"] = data.pop("cameraId")
        data["smartDetectEvents"] = data.pop("smartDetectEventsIds")
        data["thumbnail"] = data.pop("thumbnailId")
        data["user"] = data.pop("userId")

        return data

    @property
    def camera(self) -> Optional[Camera]:
        if self.camera_id is None:
            return None

        if self._api is None:
            raise NvrError("API Client not initialized")

        return self._api.bootstrap.cameras[self.camera_id]

    @property
    def user(self) -> Optional[User]:
        if self.user_id is None:
            return None

        if self._api is None:
            raise NvrError("API Client not initialized")

        return self._api.bootstrap.users[self.user_id]


class Group(ProtectModelWithId):
    name: str
    permissions: List[str]
    type: str
    is_default: bool


class UserLocation(ProtectModel):
    is_away: bool
    latitude: Optional[float]
    longitude: Optional[float]


class NVRLocation(UserLocation):
    is_geofencing_enabled: bool
    radius: int
    model: Optional[ModelType] = None


class CloudAccount(ProtectModelWithId):
    first_name: str
    last_name: str
    email: str
    user_id: str
    name: str
    location: UserLocation
    # TODO:
    # profileImg

    def __init__(self, **kwargs):
        kwargs["location"] = UserLocation(**kwargs["location"], api=kwargs["api"])
        kwargs["user_id"] = kwargs.pop("user")

        super().__init__(**kwargs)

    def unifi_dict(self):
        data = super().unifi_dict()
        data["location"] = self.location.unifi_dict()
        data["user"] = data.pop("userId")
        data["cloudId"] = data["id"]

        return data

    @property
    def user(self) -> User:
        if self._api is None:
            raise NvrError("API Client not initialized")

        return self._api.bootstrap.users[self.user_id]


class User(ProtectModelWithId):
    permissions: List[str]
    last_login_ip: Optional[str]
    last_login_time: Optional[datetime]
    is_owner: bool
    enable_notifications: bool
    has_accepted_invite: bool
    all_permissions: List[str]
    location: UserLocation
    name: str
    first_name: str
    last_name: str
    email: str
    local_username: str
    group_ids: List[str]
    cloud_account: Optional[CloudAccount]
    # TODO:
    # settings
    # alertRules

    _groups: Optional[List[Group]] = PrivateAttr(None)

    def __init__(self, **kwargs):
        if kwargs["cloudAccount"] is not None:
            kwargs["cloudAccount"] = CloudAccount(**kwargs["cloudAccount"], api=kwargs["api"])

        kwargs["group_ids"] = kwargs.pop("groups")
        kwargs["location"] = UserLocation(**kwargs["location"], api=kwargs["api"])

        super().__init__(**kwargs)

    def unifi_dict(self):
        data = super().unifi_dict()
        data["lastLoginIp"] = None if data["lastLoginIp"] is None else str(data["lastLoginIp"])
        data["lastLoginTime"] = to_js_time(data["lastLoginTime"])
        data["groups"] = data.pop("groupIds")
        data["location"] = self.location.unifi_dict()
        if self.cloud_account is not None:
            data["cloudAccount"] = self.cloud_account.unifi_dict()

        return data

    @property
    def groups(self) -> List[Group]:
        if self._groups is not None:
            return self._groups

        if self._api is None:
            raise NvrError("API Client not initialized")

        self._groups = [self._api.bootstrap.groups[g] for g in self.group_ids]
        return self._groups


class PortConfig(ProtectBaseObject):
    ump: int
    http: int
    https: int
    rtsp: int
    rtsps: int
    rtmp: int
    devices_wss: int
    camera_https: int
    camera_tcp: int
    live_ws: int
    live_wss: int
    tcp_streams: int
    playback: int
    ems_cli: int
    ems_live_flv: int
    camera_events: int
    tcp_bridge: int
    ucore: int
    discovery_client: int

    def unifi_dict(self):
        data = super().unifi_dict()
        data["emsCLI"] = data.pop("emsCli")
        data["emsLiveFLV"] = data.pop("emsLiveFlv")
        return data


class CPUInfo(ProtectBaseObject):
    average_load: float
    temperature: float


class MemoryInfo(ProtectBaseObject):
    available: int
    free: int
    total: int


class StorageDevice(ProtectBaseObject):
    model: str
    size: int
    healthy: bool


class StorageInfo(ProtectBaseObject):
    available: int
    is_recycling: bool
    size: int
    type: str
    used: int
    devices: List[StorageDevice]


class StorageSpace(ProtectBaseObject):
    total: int
    used: int
    available: int


class TMPFSInfo(ProtectBaseObject):
    available: int
    total: int
    used: int
    path: Path

    def unifi_dict(self):
        data = super().unifi_dict()
        data["path"] = str(data["path"])
        return data


class SystemInfo(ProtectBaseObject):
    cpu: CPUInfo
    memory: MemoryInfo
    storage: StorageInfo
    tmpfs: TMPFSInfo

    def unifi_dict(self):
        data = super().unifi_dict()
        data["tmpfs"] = self.tmpfs.unifi_dict()
        return data


class DoorbellMessage(ProtectBaseObject):
    type: DoorbellMessageType
    text: str


class DoorbellSettings(ProtectBaseObject):
    default_message_text: str
    default_message_reset_timeout: timedelta
    all_messages: List[DoorbellMessage]

    # TODO
    # customMessages

    def __init__(self, **kwargs):
        kwargs["default_message_reset_timeout"] = timedelta(milliseconds=kwargs.pop("defaultMessageResetTimeoutMs"))

        super().__init__(**kwargs)

    def unifi_dict(self):
        data = super().unifi_dict()
        data["defaultMessageResetTimeoutMs"] = to_ms(data.pop("defaultMessageResetTimeout"))

        return data


class StorageStats(ProtectBaseObject):
    utilization: float
    capacity: int
    remaining_capacity: int
    recording_space: StorageSpace


class NVR(ProtectDeviceModel):
    can_auto_update: bool
    is_stats_gathering_enabled: bool
    timezone: tzinfo
    version: str
    ucore_version: str
    hardware_platform: str
    ports: PortConfig
    last_update_at: datetime
    is_station: bool
    enable_automatic_backups: bool
    enable_stats_reporting: bool
    release_channel: str
    hosts: List[IPv4Address]
    enable_bridge_auto_adoption: bool
    hardware_id: UUID
    host_type: int
    host_shortname: str
    is_hardware: bool
    is_wireless_uplink_enabled: bool
    time_format: Literal["12h", "24h"]
    temperature_unit: Literal["C", "F"]
    recording_retention_duration: timedelta
    enable_crash_reporting: bool
    disable_audio: bool
    analytics_data: str
    anonymous_device_id: UUID
    camera_utilization: int
    is_recycling: bool
    avg_motions: List[float]
    disable_auto_link: bool
    location_settings: NVRLocation
    system_info: SystemInfo
    doorbell_settings: DoorbellSettings
    storage_stats: StorageStats
    is_away: bool
    is_setup: bool
    network: str
    is_recording_disabled: bool
    is_recording_motion_only: bool
    max_camera_capacity: Dict[Literal["4K", "HD"], int]

    # TODO:
    # uiVersion
    # errorCode
    # wifiSettings
    # featureFlags
    # smartDetectAgreement

    def __init__(self, **kwargs):
        kwargs["lastUpdateAt"] = process_datetime(kwargs, "lastUpdateAt")
        kwargs["recording_retention_duration"] = timedelta(milliseconds=kwargs.pop("recordingRetentionDurationMs"))
        kwargs["timezone"] = pytz.timezone(kwargs["timezone"])
        kwargs["locationSettings"] = NVRLocation(**kwargs["locationSettings"], api=kwargs["api"])

        super().__init__(**kwargs)

    def unifi_dict(self):
        data = super().unifi_dict()
        data["timezone"] = str(data["timezone"])
        data["ports"] = self.ports.unifi_dict()
        data["lastUpdateAt"] = to_js_time(data["lastUpdateAt"])
        data["hosts"] = [str(i) for i in self.hosts]
        data["hardwareId"] = str(data["hardwareId"])
        data["recordingRetentionDurationMs"] = to_ms(data.pop("recordingRetentionDuration"))
        data["anonymousDeviceId"] = str(data["anonymousDeviceId"])
        data["locationSettings"] = self.location_settings.unifi_dict()
        data["systemInfo"] = self.system_info.unifi_dict()
        data["doorbellSettings"] = self.doorbell_settings.unifi_dict()
        data["storageStats"] = self.storage_stats.unifi_dict()
        data["maxCameraCapacity"] = {"4K": data["maxCameraCapacity"]["4k"], "HD": data["maxCameraCapacity"]["hd"]}

        return data


class Light(ProtectMotionDeviceModel):
    is_pir_motion_detected: bool
    is_light_on: bool
    is_locating: bool
    is_camera_paired: bool

    # TODO:
    # lightDeviceSettings
    # lightOnSettings
    # lightModeSettings
    # camera


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
    is_name_enabled: bool
    is_date_enabled: bool
    is_logo_enabled: bool
    is_debug_enabled: bool


class LEDSettings(ProtectBaseObject):
    is_enabled: bool
    blink_rate: int


class SpeakerSettings(ProtectBaseObject):
    is_enabled: bool
    are_system_sounds_enabled: bool
    volume: int


class RecordingSettings(ProtectBaseObject):
    pre_padding: timedelta
    post_padding: timedelta
    min_motion_event_trigger: timedelta
    end_motion_event_delay: timedelta
    suppress_illumination_surge: bool
    mode: str
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

        return data


class SmartDetectSettings(ProtectBaseObject):
    object_types: List[SmartDetectObjectType]


class PIRSettings(ProtectBaseObject):
    pir_sensitivity: int
    pir_motion_clip_length: int
    timelapse_frame_interval: int
    timelapse_transfer_interval: int


class Camera(ProtectMotionDeviceModel):
    is_deleting: bool
    mic_volume: int
    is_mic_enabled: bool
    is_recording: bool
    is_motion_detected: bool
    phy_rate: int
    hdr_mode: bool
    video_mode: str
    is_probing_for_wifi: bool
    chime_duration: int
    last_ring: Optional[datetime]
    is_live_heatmap_enabled: bool
    anonymous_device_id: UUID
    event_stats: CameraEventStats
    channels: List[CameraChannel]
    isp_settings: ISPSettings
    osd_settings: OSDSettings
    led_settings: LEDSettings
    speaker_settings: SpeakerSettings
    recording_settings: RecordingSettings
    smart_detect_settings: SmartDetectSettings
    pir_settings: PIRSettings
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
    # talkbackSettings
    # recordingSchedule
    # motionZones
    # privacyZones
    # smartDetectZones
    # smartDetectLines
    # stats
    # featureFlags
    # lcdMessage

    def unifi_dict(self):
        data = super().unifi_dict()
        data["lastRing"] = to_js_time(data["lastRing"])
        data["anonymousDeviceId"] = str(data["anonymousDeviceId"])
        data["recordingSettings"] = self.recording_settings.unifi_dict()
        data["eventStats"] = self.event_stats.unifi_dict()
        data["channels"] = [c.unifi_dict() for c in self.channels]

        return data


class LiveviewSlot(ProtectBaseObject):
    camera_ids: List[str]
    cycle_mode: str
    cycle_interval: int

    _cameras: Optional[List[Camera]] = PrivateAttr(None)

    def __init__(self, **kwargs):
        kwargs["camera_ids"] = kwargs.pop("cameras")

        super().__init__(**kwargs)

    def unifi_dict(self):
        data = super().unifi_dict()
        data["cameras"] = data.pop("cameraIds")

        return data

    @property
    def cameras(self) -> List[Camera]:
        if self._cameras is not None:
            return self._cameras

        if self._api is None:
            raise NvrError("API Client not initialized")

        self._cameras = [self._api.bootstrap.cameras[g] for g in self.camera_ids]
        return self._cameras


class Liveview(ProtectModelWithId):
    name: str
    is_default: bool
    is_global: bool
    layout: int
    slots: List[LiveviewSlot]
    owner_id: str

    def __init__(self, **kwargs):
        kwargs["owner_id"] = kwargs.pop("owner")

        slots: List[LiveviewSlot] = []
        for slot in kwargs["slots"]:
            slots.append(LiveviewSlot(**slot, api=kwargs["api"]))
        kwargs["slots"] = slots

        super().__init__(**kwargs)

    def unifi_dict(self):
        data = super().unifi_dict()
        data["owner"] = data.pop("ownerId")
        data["slots"] = [o.unifi_dict() for o in self.slots]

        return data

    @property
    def owner(self):
        if self._api is None:
            raise NvrError("API Client not initialized")

        return self._api.bootstrap.users[self.owner_id]


class Viewer(ProtectAdoptableDeviceModel):
    stream_limit: int
    software_version: str
    liveview_id: str

    def __init__(self, **kwargs):
        kwargs["liveview_id"] = kwargs.pop("liveview")

        super().__init__(**kwargs)

    @property
    def liveview(self):
        if self._api is None:
            raise NvrError("API Client not initialized")

        return self._api.bootstrap.liveviews[self.liveview_id]

    def unifi_dict(self):
        data = super().unifi_dict()
        data["liveview"] = data.pop("liveviewId")

        return data


class Bootstrap(ProtectBaseObject):
    auth_user_id: str
    access_key: str
    cameras: Dict[str, Camera]
    users: Dict[str, User]
    groups: Dict[str, Group]
    liveviews: Dict[str, Liveview]
    nvr: NVR
    viewers: Dict[str, Viewer]
    lights: Dict[str, Light]
    last_update_id: UUID

    # TODO:
    # legacyUFVs
    # displays
    # bridges
    # sensors
    # doorlocks

    def __init__(self, **kwargs):
        kwargs["nvr"] = NVR(**kwargs["nvr"], api=kwargs.get("api"))

        for key in SUPPORTED_PROTECT_MODELS:
            items: Dict[str, ProtectModelWithId] = {}
            for item in kwargs[key]:
                items[item["id"]] = ProtectModel.from_unifi_dict(item, api=kwargs.get("api"))
            kwargs[key] = items

        super().__init__(**kwargs)

    def unifi_dict(self):
        data = super().unifi_dict()
        data["lastUpdateId"] = str(data["lastUpdateId"])
        data["cameras"] = [o.unifi_dict() for o in self.cameras.values()]
        data["users"] = [o.unifi_dict() for o in self.users.values()]
        data["groups"] = [o.unifi_dict() for o in self.groups.values()]
        data["liveviews"] = [o.unifi_dict() for o in self.liveviews.values()]
        data["viewers"] = [o.unifi_dict() for o in self.viewers.values()]
        data["lights"] = [o.unifi_dict() for o in self.lights.values()]
        data["nvr"] = self.nvr.unifi_dict()

        return data

    @property
    def auth_user(self) -> User:
        if self._api is None:
            raise NvrError("API Client not initialized")

        return self._api.bootstrap.users[self.auth_user_id]
