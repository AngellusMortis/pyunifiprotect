"""Unifi Protect Data."""
from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from ipaddress import IPv4Address
import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set
from uuid import UUID

from pydantic.fields import PrivateAttr
import pytz

from pyunifiprotect.data.base import (
    ProtectBaseObject,
    ProtectDeviceModel,
    ProtectModel,
    ProtectModelWithId,
)
from pyunifiprotect.data.devices import Bridge, Camera, Light, Sensor, Viewer
from pyunifiprotect.data.types import (
    DoorbellMessageType,
    EventType,
    FixSizeOrderedDict,
    ModelType,
    SmartDetectObjectType,
)
from pyunifiprotect.data.websocket import WSJSONPacketFrame, WSPacket
from pyunifiprotect.utils import process_datetime

_LOGGER = logging.getLogger(__name__)

MAX_SUPPORTED_CAMERAS = 256
MAX_EVENT_HISTORY_IN_STATE_MACHINE = MAX_SUPPORTED_CAMERAS * 2


class Event(ProtectModelWithId):
    type: EventType
    start: datetime
    end: Optional[datetime]
    score: int
    heatmap_id: Optional[str]
    camera_id: Optional[str]
    smart_detect_types: List[SmartDetectObjectType]
    smart_detect_event_ids: List[str]
    thumbnail_id: Optional[str]
    user_id: Optional[str]

    # TODO:
    # metadata
    # partition

    _smart_detect_events: Optional[List[Event]] = PrivateAttr(None)

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "camera": "cameraId",
            "heatmap": "heatmapId",
            "user": "userId",
            "thumbnail": "thumbnailId",
            "smartDetectEvents": "smartDetectEventIds",
        }

    @classmethod
    def clean_unifi_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "start" in data:
            data["start"] = process_datetime(data, "start")
        if "end" in data:
            data["end"] = process_datetime(data, "end")

        return super().clean_unifi_dict(data)

    @property
    def camera(self) -> Optional[Camera]:
        if self.camera_id is None:
            return None

        return self.api.bootstrap.cameras[self.camera_id]

    @property
    def user(self) -> Optional[User]:
        if self.user_id is None:
            return None

        return self.api.bootstrap.users.get(self.user_id)

    @property
    def smart_detect_events(self) -> List[Event]:
        if self._smart_detect_events is not None:
            return self._smart_detect_events

        self._smart_detect_events = [
            self.api.bootstrap.events[g] for g in self.smart_detect_event_ids if g in self.api.bootstrap.events
        ]
        return self._smart_detect_events


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

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {**super()._get_unifi_remaps(), "user": "userId"}

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        # id and cloud ID are always the same
        if "id" in data:
            data["cloudId"] = data["id"]

        return data

    @property
    def user(self) -> User:
        return self.api.bootstrap.users[self.user_id]


class UserFeatureFlags(ProtectBaseObject):
    notifications_v2: bool


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
    feature_flags: UserFeatureFlags

    # TODO:
    # settings
    # alertRules
    # notificationsV2

    _groups: Optional[List[Group]] = PrivateAttr(None)

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {**super()._get_unifi_remaps(), "groups": "groupIds"}

    @property
    def groups(self) -> List[Group]:
        """
        Groups the user is in

        Will always be empty if the user only has read only access.
        """

        if self._groups is not None:
            return self._groups

        self._groups = [self.api.bootstrap.groups[g] for g in self.group_ids if g in self.api.bootstrap.groups]
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

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "emsCLI": "emsCli",
            "emsLiveFLV": "emsLiveFlv",
        }


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


class SystemInfo(ProtectBaseObject):
    cpu: CPUInfo
    memory: MemoryInfo
    storage: StorageInfo
    tmpfs: TMPFSInfo


class DoorbellMessage(ProtectBaseObject):
    type: DoorbellMessageType
    text: str


class DoorbellSettings(ProtectBaseObject):
    default_message_text: str
    default_message_reset_timeout: timedelta
    all_messages: List[DoorbellMessage]

    # TODO
    # customMessages

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {**super()._get_unifi_remaps(), "defaultMessageResetTimeoutMs": "defaultMessageResetTimeout"}

    @classmethod
    def clean_unifi_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "defaultMessageResetTimeoutMs" in data:
            data["defaultMessageResetTimeout"] = timedelta(milliseconds=data.pop("defaultMessageResetTimeoutMs"))

        return super().clean_unifi_dict(data)


class RecordingTypeDistribution(ProtectBaseObject):
    recording_type: str
    size: int
    percentage: float


class ResolutionDistribution(ProtectBaseObject):
    resolution: str
    size: int
    percentage: float


class StorageDistribution(ProtectBaseObject):
    recording_type_distributions: List[RecordingTypeDistribution]
    resolution_distributions: List[ResolutionDistribution]


class StorageStats(ProtectBaseObject):
    utilization: float
    capacity: int
    remaining_capacity: int
    recording_space: StorageSpace
    storage_distribution: StorageDistribution


class NVRFeatureFlags(ProtectBaseObject):
    beta: bool
    dev: bool
    notifications_v2: bool


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
    skip_firmware_update: bool
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
    max_camera_capacity: Dict[Literal["4K", "2K", "HD"], int]

    # TODO:
    # uiVersion
    # errorCode
    # wifiSettings
    # smartDetectAgreement
    # ssoChannel

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {**super()._get_unifi_remaps(), "recordingRetentionDurationMs": "recordingRetentionDuration"}

    @classmethod
    def clean_unifi_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "lastUpdateAt" in data:
            data["lastUpdateAt"] = process_datetime(data, "lastUpdateAt")
        if "recordingRetentionDurationMs" in data:
            data["recordingRetentionDuration"] = timedelta(milliseconds=data.pop("recordingRetentionDurationMs"))
        if "timezone" in data and not isinstance(data["timezone"], tzinfo):
            data["timezone"] = pytz.timezone(data["timezone"])

        data = super().clean_unifi_dict(data)

        return data


class LiveviewSlot(ProtectBaseObject):
    camera_ids: List[str]
    cycle_mode: str
    cycle_interval: int

    _cameras: Optional[List[Camera]] = PrivateAttr(None)

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {**super()._get_unifi_remaps(), "cameras": "cameraIds"}

    @property
    def cameras(self) -> List[Camera]:
        if self._cameras is not None:
            return self._cameras

        self._cameras = [self.api.bootstrap.cameras[g] for g in self.camera_ids]
        return self._cameras


class Liveview(ProtectModelWithId):
    name: str
    is_default: bool
    is_global: bool
    layout: int
    slots: List[LiveviewSlot]
    owner_id: str

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {**super()._get_unifi_remaps(), "owner": "ownerId"}

    @property
    def owner(self) -> Optional[User]:
        """
        Owner of liveview.

        Will be none if the user only has read only access and it was not made by their user.
        """

        return self.api.bootstrap.users.get(self.owner_id)


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
    bridges: Dict[str, Bridge]
    sensors: Dict[str, Sensor]
    last_update_id: UUID

    # TODO:
    # legacyUFVs
    # displays
    # doorlocks
    # chimes
    # schedules

    # not directly from Unifi
    events: Dict[str, Event] = FixSizeOrderedDict()

    @classmethod
    def clean_unifi_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        for model_type in ModelType.bootstrap_models():
            key = model_type + "s"
            items: Dict[str, ProtectModel] = {}
            for item in data[key]:
                items[item["id"]] = item
            data[key] = items

        return super().clean_unifi_dict(data)

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "events" in data:
            del data["events"]

        for model_type in ModelType.bootstrap_models():
            attr = model_type + "s"
            if attr in data and isinstance(data[attr], dict):
                data[attr] = list(data[attr].values())

        return data

    @property
    def auth_user(self) -> User:
        user: User = self._api.bootstrap.users[self.auth_user_id]
        return user

    def process_event(self, event: Event) -> None:
        if event.camera is None:
            return

        if event.type == EventType.MOTION:
            if event.end is None:
                event.camera.is_motion_detected = True
            else:
                event.camera.is_motion_detected = False

                event.camera.last_motion = event.end
                event.camera.last_motion_event_id = event.id
        elif event.type == EventType.SMART_DETECT:
            if event.end is not None:
                event.camera.last_smart_detect = event.end
                event.camera.last_smart_detect_event_id = event.id
        elif event.type == EventType.RING:
            event.camera.last_ring = event.start
            event.camera.last_ring_event_id = event.id

        self.events[event.id] = event

    def process_ws_packet(self, packet: WSPacket) -> None:
        if not isinstance(packet.action_frame, WSJSONPacketFrame):
            _LOGGER.debug("Unexpected action frame format: %s", packet.action_frame.payload_format)

        if not isinstance(packet.data_frame, WSJSONPacketFrame):
            _LOGGER.debug("Unexpected data frame format: %s", packet.data_frame.payload_format)

        action: dict = packet.action_frame.data  # type: ignore
        data: dict = packet.data_frame.data  # type: ignore
        self.last_update_id = UUID(action["newUpdateId"])

        if action["modelKey"] not in ModelType.values():
            _LOGGER.debug("Unknown model type: %s", action["modelKey"])
            return

        if action["action"] == "add":
            obj = ProtectModel.from_unifi_dict(data, api=self._api)

            if isinstance(obj, Event):
                self.process_event(obj)
            elif (
                isinstance(obj, ProtectModelWithId)
                and obj.model is not None
                and obj.model.value in ModelType.bootstrap_models()
            ):
                key = obj.model.value + "s"
                getattr(self, key)[obj.id] = obj
            else:
                _LOGGER.debug("Unexpected bootstrap model type for add: %s", obj.model)
        elif action["action"] == "update":
            model_type = action["modelKey"]
            if model_type in ModelType.bootstrap_models() or model_type == ModelType.EVENT.value:
                key = model_type + "s"
                devices = getattr(self, key)
                if action["id"] in devices:
                    obj: ProtectModel = devices[action["id"]]
                    obj = obj.update_from_unifi_dict(data)

                    if isinstance(obj, Event):
                        self.process_event(obj)

                    devices[action["id"]] = obj
                # ignore updates to events that phase out
                elif model_type != ModelType.EVENT.value:
                    _LOGGER.debug("Unexpected %s: %s", key, action["id"])
            else:
                _LOGGER.debug("Unexpected bootstrap model type for update: %s", model_type)
