"""Unifi Protect Data."""
from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from ipaddress import IPv4Address
from pathlib import Path
from typing import Dict, List, Literal, Optional
from uuid import UUID

from pydantic.fields import PrivateAttr
import pytz

from ..exceptions import NvrError
from ..utils import process_datetime, to_js_time, to_ms
from .base import (
    ProtectBaseObject,
    ProtectDeviceModel,
    ProtectModel,
    ProtectModelWithId,
)
from .devices import Camera, Light, Viewer
from .types import DoorbellMessageType, EventType, ModelType, SmartDetectObjectType

SUPPORTED_PROTECT_MODELS = ["cameras", "users", "groups", "liveviews", "viewers", "lights"]


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

        return self._api.bootstrap.users.get(self.user_id)


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
        """
        Groups the user is in

        Will always be empty if the user only has read only access.
        """

        if self._groups is not None:
            return self._groups

        if self._api is None:
            raise NvrError("API Client not initialized")

        self._groups = [self._api.bootstrap.groups[g] for g in self.group_ids if g in self._api.bootstrap.groups]
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


class NVRFeatureFlags(ProtectBaseObject):
    beta: bool
    dev: bool


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
    feature_flags: NVRFeatureFlags
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
    def owner(self) -> Optional[User]:
        """
        Owner of liveview.

        Will be none if the user only has read only access and it was not made by their user.
        """

        if self._api is None:
            raise NvrError("API Client not initialized")

        return self._api.bootstrap.users.get(self.owner_id)


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
