"""Unifi Protect Data."""
from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from ipaddress import IPv4Address
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Dict,
    List,
    Literal,
    Optional,
    Set,
    Tuple,
    Union,
)
from uuid import UUID

from pydantic.fields import PrivateAttr
import pytz

from pyunifiprotect.data.base import (
    ProtectBaseObject,
    ProtectDeviceModel,
    ProtectModel,
    ProtectModelWithId,
)
from pyunifiprotect.data.devices import Camera, CameraZone, Light, Sensor
from pyunifiprotect.data.types import (
    DoorbellMessageType,
    DoorbellText,
    EventType,
    ModelType,
    MountType,
    PercentInt,
    RecordingType,
    ResolutionStorageType,
    SensorStatusType,
    SensorType,
    SmartDetectObjectType,
    Version,
)
from pyunifiprotect.exceptions import BadRequest
from pyunifiprotect.utils import process_datetime

if TYPE_CHECKING:
    from pydantic.typing import SetStr

MAX_SUPPORTED_CAMERAS = 256
MAX_EVENT_HISTORY_IN_STATE_MACHINE = MAX_SUPPORTED_CAMERAS * 2


class SmartDetectItem(ProtectBaseObject):
    id: str
    timestamp: datetime
    level: PercentInt
    coord: Tuple[int, int, int, int]
    object_type: SmartDetectObjectType
    zone_ids: List[int]
    duration: timedelta

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "zones": "zoneIds",
        }

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "duration" in data:
            data["duration"] = timedelta(milliseconds=data["duration"])

        return super().unifi_dict_to_dict(data)


class SmartDetectTrack(ProtectBaseObject):
    id: str
    payload: List[SmartDetectItem]
    camera_id: str
    event_id: str

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "camera": "cameraId",
            "event": "eventId",
        }

    @property
    def camera(self) -> Camera:
        return self.api.bootstrap.cameras[self.camera_id]

    @property
    def event(self) -> Optional[Event]:
        return self.api.bootstrap.events.get(self.event_id)


class EventMetadata(ProtectBaseObject):
    client_platform: Optional[str]
    reason: Optional[str]
    app_update: Optional[str]
    light_id: Optional[str]
    light_name: Optional[str]
    type: Optional[str]
    sensor_id: Optional[str]
    sensor_name: Optional[str]
    sensor_type: Optional[SensorType]
    doorlock_id: Optional[str]
    doorlock_name: Optional[str]
    from_value: Optional[str]
    to_value: Optional[str]
    mount_type: Optional[MountType]
    status: Optional[SensorStatusType]
    alarm_type: Optional[str]

    _collapse_keys: ClassVar[SetStr] = {
        "lightId",
        "lightName",
        "type",
        "sensorId",
        "sensorName",
        "sensorType",
        "doorlockId",
        "doorlockName",
        "mountType",
        "status",
        "alarmType",
    }

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {
            **super()._get_unifi_remaps(),
            "from": "fromValue",
            "to": "toValue",
        }

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        for key in cls._collapse_keys.intersection(data.keys()):
            data[key] = data[key]["text"]

        return super().unifi_dict_to_dict(data)

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        # all metadata keys optionally appear
        for key, value in list(data.items()):
            if value is None:
                del data[key]

        for key in self._collapse_keys.intersection(data.keys()):
            data[key] = {"text": data[key]}

        return data


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
    timestamp: Optional[datetime]
    metadata: Optional[EventMetadata]

    # TODO:
    # partition

    _smart_detect_events: Optional[List[Event]] = PrivateAttr(None)
    _smart_detect_track: Optional[SmartDetectTrack] = PrivateAttr(None)
    _smart_detect_zones: Optional[Dict[int, CameraZone]] = PrivateAttr(None)

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
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        for key in {"start", "end", "timestamp"}.intersection(data.keys()):
            data[key] = process_datetime(data, key)

        return super().unifi_dict_to_dict(data)

    @property
    def camera(self) -> Optional[Camera]:
        if self.camera_id is None:
            return None

        return self.api.bootstrap.cameras.get(self.camera_id)

    @property
    def light(self) -> Optional[Light]:
        if self.metadata is None or self.metadata.light_id is None:
            return None

        return self.api.bootstrap.lights.get(self.metadata.light_id)

    @property
    def sensor(self) -> Optional[Sensor]:
        if self.metadata is None or self.metadata.sensor_id is None:
            return None

        return self.api.bootstrap.sensors.get(self.metadata.sensor_id)

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

    async def get_thumbnail(self, width: Optional[int] = None, height: Optional[int] = None) -> Optional[bytes]:
        """Gets thumbnail for event"""

        if self.thumbnail_id is None:
            return None
        return await self.api.get_event_thumbnail(self.thumbnail_id, width, height)

    async def get_heatmap(self) -> Optional[bytes]:
        """Gets heatmap for event"""

        if self.heatmap_id is None:
            return None
        return await self.api.get_event_heatmap(self.heatmap_id)

    async def get_video(self, channel_index: int = 0) -> Optional[bytes]:
        """Get the MP4 video clip for this given event

        Args:

        * `channel_index`: index of `CameraChannel` on the camera to use to retrieve video from

        Will raise an exception if event does not have a camera, end time or the channel index is wrong.
        """

        if self.camera is None:
            raise BadRequest("Event does not have a camera")
        if self.end is None:
            raise BadRequest("Event is ongoing")

        return await self.api.get_camera_video(self.camera.id, self.start, self.end, channel_index)

    async def get_smart_detect_track(self) -> SmartDetectTrack:
        """
        Gets smart detect track for given smart detect event.

        If event is not a smart detect event, it will raise a `BadRequest`
        """

        if self.type != EventType.SMART_DETECT:
            raise BadRequest("Not a smart detect event")

        if self._smart_detect_track is None:
            self._smart_detect_track = await self.api.get_event_smart_detect_track(self.id)

        return self._smart_detect_track

    async def get_smart_detect_zones(self) -> Dict[int, CameraZone]:
        """Gets the triggering zones for the smart detection"""

        if self.camera is None:
            raise BadRequest("No camera on event")

        if self._smart_detect_zones is None:
            smart_track = await self.get_smart_detect_track()

            ids: Set[int] = set()
            for item in smart_track.payload:
                ids = ids | set(item.zone_ids)

            self._smart_detect_zones = {z.id: z for z in self.camera.smart_detect_zones if z.id in ids}

        return self._smart_detect_zones


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
    location: Optional[UserLocation]

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
        if "location" in data and data["location"] is None:
            del data["location"]

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
    scopes: List[str]
    location: Optional[UserLocation]
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

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "location" in data and data["location"] is None:
            del data["location"]

        return data

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
    piongw: Optional[int] = None

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
    available: Optional[int]
    free: Optional[int]
    total: Optional[int]


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

    # TODO:
    # ustorage


class DoorbellMessage(ProtectBaseObject):
    type: DoorbellMessageType
    text: DoorbellText


class DoorbellSettings(ProtectBaseObject):
    default_message_text: DoorbellText
    default_message_reset_timeout: timedelta
    all_messages: List[DoorbellMessage]
    custom_messages: List[DoorbellText]

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {**super()._get_unifi_remaps(), "defaultMessageResetTimeoutMs": "defaultMessageResetTimeout"}

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "defaultMessageResetTimeoutMs" in data:
            data["defaultMessageResetTimeout"] = timedelta(milliseconds=data.pop("defaultMessageResetTimeoutMs"))

        return super().unifi_dict_to_dict(data)


class RecordingTypeDistribution(ProtectBaseObject):
    recording_type: RecordingType
    size: int
    percentage: float


class ResolutionDistribution(ProtectBaseObject):
    resolution: ResolutionStorageType
    size: int
    percentage: float


class StorageDistribution(ProtectBaseObject):
    recording_type_distributions: List[RecordingTypeDistribution]
    resolution_distributions: List[ResolutionDistribution]

    _recording_type_dict: Optional[Dict[RecordingType, RecordingTypeDistribution]] = PrivateAttr(None)
    _resolution_dict: Optional[Dict[ResolutionStorageType, ResolutionDistribution]] = PrivateAttr(None)

    def _get_recording_type_dict(self) -> Dict[RecordingType, RecordingTypeDistribution]:
        if self._recording_type_dict is None:
            self._recording_type_dict = {}
            for recording_type in self.recording_type_distributions:
                self._recording_type_dict[recording_type.recording_type] = recording_type

        return self._recording_type_dict

    def _get_resolution_dict(self) -> Dict[ResolutionStorageType, ResolutionDistribution]:
        if self._resolution_dict is None:
            self._resolution_dict = {}
            for resolution in self.resolution_distributions:
                self._resolution_dict[resolution.resolution] = resolution

        return self._resolution_dict

    @property
    def timelapse_recordings(self) -> Optional[RecordingTypeDistribution]:
        return self._get_recording_type_dict().get(RecordingType.TIMELAPSE)

    @property
    def continuous_recordings(self) -> Optional[RecordingTypeDistribution]:
        return self._get_recording_type_dict().get(RecordingType.CONTINUOUS)

    @property
    def detections_recordings(self) -> Optional[RecordingTypeDistribution]:
        return self._get_recording_type_dict().get(RecordingType.DETECTIONS)

    @property
    def uhd_usage(self) -> Optional[ResolutionDistribution]:
        return self._get_resolution_dict().get(ResolutionStorageType.UHD)

    @property
    def hd_usage(self) -> Optional[ResolutionDistribution]:
        return self._get_resolution_dict().get(ResolutionStorageType.HD)

    @property
    def free(self) -> Optional[ResolutionDistribution]:
        return self._get_resolution_dict().get(ResolutionStorageType.FREE)

    def update_from_dict(self, data: Dict[str, Any]) -> StorageDistribution:
        # reset internal look ups when data changes
        self._recording_type_dict = None
        self._resolution_dict = None

        return super().update_from_dict(data)


class StorageStats(ProtectBaseObject):
    utilization: float
    capacity: Optional[timedelta]
    remaining_capacity: Optional[timedelta]
    recording_space: StorageSpace
    storage_distribution: StorageDistribution

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "capacity" in data and data["capacity"] is not None:
            data["capacity"] = timedelta(milliseconds=data.pop("capacity"))
        if "remainingCapacity" in data and data["remainingCapacity"] is not None:
            data["remainingCapacity"] = timedelta(milliseconds=data.pop("remainingCapacity"))

        return super().unifi_dict_to_dict(data)


class NVRFeatureFlags(ProtectBaseObject):
    beta: bool
    dev: bool
    notifications_v2: bool


class NVR(ProtectDeviceModel):
    can_auto_update: bool
    is_stats_gathering_enabled: bool
    timezone: tzinfo
    version: Version
    ucore_version: str
    hardware_platform: str
    ports: PortConfig
    last_update_at: Optional[datetime]
    is_station: bool
    enable_automatic_backups: bool
    enable_stats_reporting: bool
    release_channel: str
    hosts: List[Union[IPv4Address, str]]
    enable_bridge_auto_adoption: bool
    hardware_id: UUID
    host_type: int
    host_shortname: str
    is_hardware: bool
    is_wireless_uplink_enabled: bool
    time_format: Literal["12h", "24h"]
    temperature_unit: Literal["C", "F"]
    recording_retention_duration: Optional[timedelta]
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
    is_wireless_uplink_enabled: Optional[bool]
    market_name: Optional[str] = None
    stream_sharing_available: Optional[bool] = None
    is_db_available: Optional[bool] = None
    is_recording_disabled: Optional[bool] = None
    is_recording_motion_only: Optional[bool] = None

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
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "lastUpdateAt" in data:
            data["lastUpdateAt"] = process_datetime(data, "lastUpdateAt")
        if "recordingRetentionDurationMs" in data and data["recordingRetentionDurationMs"] is not None:
            data["recordingRetentionDuration"] = timedelta(milliseconds=data.pop("recordingRetentionDurationMs"))
        if "timezone" in data and not isinstance(data["timezone"], tzinfo):
            data["timezone"] = pytz.timezone(data["timezone"])

        return super().unifi_dict_to_dict(data)

    async def _api_update(self, data: Dict[str, Any]) -> None:
        return await self.api.update_nvr(data)

    @property
    def protect_url(self) -> str:
        return f"{self.api.base_url}/protect/devices/{self.api.bootstrap.nvr.id}"

    def update_all_messages(self) -> None:
        """Updates doorbell_settings.all_messages after adding/removing custom message"""

        messages = self.doorbell_settings.custom_messages
        self.doorbell_settings.all_messages = [
            DoorbellMessage(
                type=DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR,
                text=DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR.value.replace("_", " "),
            ),
            DoorbellMessage(
                type=DoorbellMessageType.DO_NOT_DISTURB,
                text=DoorbellMessageType.DO_NOT_DISTURB.value.replace("_", " "),
            ),
            *(
                DoorbellMessage(
                    type=DoorbellMessageType.CUSTOM_MESSAGE,
                    text=message,
                )
                for message in messages
            ),
        ]
        self._initial_data = self.dict()

    async def set_default_reset_timeout(self, timeout: timedelta) -> None:
        """Sets the default message reset timeout"""

        self.doorbell_settings.default_message_reset_timeout = timeout
        await self.save_device()

    async def set_default_doorbell_message(self, message: str) -> None:
        """Sets default doorbell message"""

        self.doorbell_settings.default_message_text = DoorbellText(message)
        await self.save_device()

    async def add_custom_doorbell_message(self, message: str) -> None:
        """Adds custom doorbell message"""

        if len(message) > 30:
            raise BadRequest("Message length over 30 characters")

        if message in self.doorbell_settings.custom_messages:
            raise BadRequest("Custom doorbell message already exists")

        self.doorbell_settings.custom_messages.append(DoorbellText(message))
        await self.save_device()
        self.update_all_messages()

    async def remove_custom_doorbell_message(self, message: str) -> None:
        """Removes custom doorbell message"""

        if message not in self.doorbell_settings.custom_messages:
            raise BadRequest("Custom doorbell message does not exists")

        self.doorbell_settings.custom_messages.remove(DoorbellText(message))
        await self.save_device()
        self.update_all_messages()


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

        # user may not have permission to see the cameras in the liveview
        self._cameras = [self.api.bootstrap.cameras[g] for g in self.camera_ids if g in self.api.bootstrap.cameras]
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

    @property
    def protect_url(self) -> str:
        return f"{self.api.base_url}/protect/liveview/{self.id}"
