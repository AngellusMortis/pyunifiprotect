from __future__ import annotations

import enum
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    List,
    Literal,
    Optional,
    TypeVar,
    Union,
)

from packaging.version import Version as BaseVersion
from pydantic import ConstrainedInt
from pydantic.color import Color as BaseColor
from pydantic.types import ConstrainedFloat, ConstrainedStr

KT = TypeVar("KT")
VT = TypeVar("VT")


DEFAULT = "DEFAULT_VALUE"
DEFAULT_TYPE = Literal["DEFAULT_VALUE"]

ProgressCallback = Callable[[int, int, int], Coroutine[Any, Any, None]]
IteratorCallback = Callable[[int, Optional[bytes]], Coroutine[Any, Any, None]]


class FixSizeOrderedDict(dict[KT, VT]):
    """A fixed size ordered dict."""

    def __init__(self, *args: Any, max_size: int = 0, **kwargs: Any) -> None:
        """Create the FixSizeOrderedDict."""
        self._max_size = max_size
        super().__init__(*args, **kwargs)

    def __setitem__(self, key: KT, value: VT) -> None:
        """Set an update up to the max size."""
        dict.__setitem__(self, key, value)
        if self._max_size > 0 and len(self) > 0 and len(self) > self._max_size:
            del self[list(self.keys())[0]]


class ValuesEnumMixin:
    _values: Optional[List[str]] = None
    _values_normalized: Optional[Dict[str, str]] = None

    @classmethod
    def values(cls) -> List[str]:
        if cls._values is None:
            cls._values = [e.value for e in cls]  # type: ignore
        return cls._values

    @classmethod
    def _missing_(cls, value: Any) -> Optional[Any]:
        if cls._values_normalized is None:
            cls._values_normalized = {e.value.lower(): e for e in cls}  # type: ignore

        value_normal = value
        if isinstance(value, str):
            value_normal = value.lower()
        return cls._values_normalized.get(value_normal)


@enum.unique
class ModelType(str, ValuesEnumMixin, enum.Enum):
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
    SCHEDULE = "schedule"
    CHIME = "chime"
    DEVICE_GROUP = "deviceGroup"
    LEGACY_UFV = "legacyUFV"
    RECORDING_SCHEDULE = "recordingSchedule"

    @staticmethod
    def bootstrap_models() -> List[str]:
        # TODO:
        # legacyUFV
        # display

        return [
            ModelType.CAMERA.value,
            ModelType.USER.value,
            ModelType.GROUP.value,
            ModelType.LIVEVIEW.value,
            ModelType.VIEWPORT.value,
            ModelType.LIGHT.value,
            ModelType.BRIDGE.value,
            ModelType.SENSOR.value,
            ModelType.DOORLOCK.value,
            ModelType.CHIME.value,
        ]


@enum.unique
class EventType(str, ValuesEnumMixin, enum.Enum):
    DISCONNECT = "disconnect"
    PROVISION = "provision"
    UPDATE = "update"
    CAMERA_POWER_CYCLE = "cameraPowerCycling"
    RING = "ring"
    RESOLUTION_LOWERED = "resolutionLowered"
    MOTION = "motion"
    RECORDING_DELETED = "recordingDeleted"
    SMART_DETECT = "smartDetectZone"
    SMART_DETECT_LINE = "smartDetectLine"
    NO_SCHEDULE = "nonScheduledRecording"
    RECORDING_MODE_CHANGED = "recordingModeChanged"
    HOTPLUG = "hotplug"
    #
    INSTALLED_DISK = "installed"
    OFFLINE = "offline"
    OFF = "off"
    REBOOT = "reboot"
    FIRMWARE_UPDATE = "fwUpdate"
    APP_UPDATE = "applicationUpdate"
    ACCESS = "access"
    DRIVE_FAILED = "driveFailed"
    CAMERA_UTILIZATION_LIMIT_REACHED = "cameraUtilizationLimitReached"
    CAMERA_UTILIZATION_LIMIT_EXCEEDED = "cameraUtilizationLimitExceeded"
    #
    MOTION_SENSOR = "sensorMotion"
    SENSOR_OPENED = "sensorOpened"
    SENSOR_CLOSED = "sensorClosed"
    SENSOR_ALARM = "sensorAlarm"
    SENSOR_EXTREME_VALUE = "sensorExtremeValues"
    SENSOR_WATER_LEAK = "sensorWaterLeak"
    SENSOR_BATTERY_LOW = "sensorBatteryLow"
    #
    MOTION_LIGHT = "lightMotion"
    #
    DOORLOCK_OPEN = "doorlockOpened"
    DOORLOCK_CLOSE = "doorlockClosed"
    DOORLOCK_BATTERY_LOW = "doorlockBatteryLow"
    #
    UNADOPTED_DEVICE_DISCOVERED = "unadoptedDeviceDiscovered"
    DEVICE_ADOPTED = "deviceAdopted"
    DEVICE_UNADOPTED = "deviceUnadopted"
    UVF_DISCOVERED = "ufvDiscovered"
    DEVICE_PASSWORD_UPDATE = "devicesPasswordUpdated"
    #
    USER_LEFT = "userLeft"
    USER_ARRIVED = "userArrived"
    VIDEO_EXPORTED = "videoExported"
    MIC_DISABLED = "microphoneDisabled"
    VIDEO_DELETED = "videoDeleted"
    SCHEDULE_CHANGED = "recordingScheduleChanged"
    #
    RECORDING_OFF = "recordingOff"

    @staticmethod
    def device_events() -> List[str]:
        return [EventType.MOTION.value, EventType.RING.value, EventType.SMART_DETECT.value]

    @staticmethod
    def motion_events() -> List[str]:
        return [EventType.MOTION.value, EventType.SMART_DETECT.value]


@enum.unique
class StateType(str, ValuesEnumMixin, enum.Enum):
    CONNECTED = "CONNECTED"
    CONNECTING = "CONNECTING"
    DISCONNECTED = "DISCONNECTED"


@enum.unique
class ProtectWSPayloadFormat(int, enum.Enum):
    """Websocket Payload formats."""

    JSON = 1
    UTF8String = 2
    NodeBuffer = 3


@enum.unique
class SmartDetectObjectType(str, ValuesEnumMixin, enum.Enum):
    PERSON = "person"
    ANIMAL = "animal"
    VEHICLE = "vehicle"
    FACE = "face"
    PET = "pet"
    LICENSE_PLATE = "licenseplate"
    PACKAGE = "package"
    # old?
    CAR = "car"


@enum.unique
class SmartDetectAudioType(str, ValuesEnumMixin, enum.Enum):
    SMOKE = "alrmSmoke"
    CMONX = "alrmCmonx"


@enum.unique
class DoorbellMessageType(str, ValuesEnumMixin, enum.Enum):
    LEAVE_PACKAGE_AT_DOOR = "LEAVE_PACKAGE_AT_DOOR"
    DO_NOT_DISTURB = "DO_NOT_DISTURB"
    CUSTOM_MESSAGE = "CUSTOM_MESSAGE"


@enum.unique
class LightModeEnableType(str, ValuesEnumMixin, enum.Enum):
    DARK = "dark"
    ALWAYS = "fulltime"
    NIGHT = "night"


@enum.unique
class LightModeType(str, ValuesEnumMixin, enum.Enum):
    MOTION = "motion"
    WHEN_DARK = "always"
    MANUAL = "off"
    SCHEDULE = "schedule"


@enum.unique
class VideoMode(str, ValuesEnumMixin, enum.Enum):
    DEFAULT = "default"
    HIGH_FPS = "highFps"
    HOMEKIT = "homekit"
    # should only be for unadopted devices
    UNKNOWN = "unknown"


@enum.unique
class RecordingMode(str, ValuesEnumMixin, enum.Enum):
    ALWAYS = "always"
    NEVER = "never"
    DETECTIONS = "detections"


@enum.unique
class AnalyticsOption(str, ValuesEnumMixin, enum.Enum):
    NONE = "none"
    ANONYMOUS = "anonymous"
    FULL = "full"


@enum.unique
class RecordingType(str, ValuesEnumMixin, enum.Enum):
    TIMELAPSE = "timelapse"
    CONTINUOUS = "rotating"
    DETECTIONS = "detections"


@enum.unique
class ResolutionStorageType(str, ValuesEnumMixin, enum.Enum):
    UHD = "4K"
    HD = "HD"
    FREE = "free"


@enum.unique
class IRLEDMode(str, ValuesEnumMixin, enum.Enum):
    AUTO = "auto"
    ON = "on"
    AUTO_NO_LED = "autoFilterOnly"
    OFF = "off"
    MANUAL = "manual"


@enum.unique
class MountType(str, ValuesEnumMixin, enum.Enum):
    NONE = "none"
    LEAK = "leak"
    DOOR = "door"
    WINDOW = "window"
    GARAGE = "garage"


@enum.unique
class SensorType(str, ValuesEnumMixin, enum.Enum):
    TEMPERATURE = "temperature"
    LIGHT = "light"
    HUMIDITY = "humidity"


@enum.unique
class SensorStatusType(str, ValuesEnumMixin, enum.Enum):
    UNKNOWN = "unknown"
    SAFE = "safe"
    NEUTRAL = "neutral"
    LOW = "low"
    HIGH = "high"


@enum.unique
class SleepStateType(str, ValuesEnumMixin, enum.Enum):
    DISCONNECTED = "disconnected"
    AWAKE = "awake"
    START_SLEEP = "goingToSleep"
    ASLEEP = "asleep"
    WAKING = "waking"


@enum.unique
class AutoExposureMode(str, ValuesEnumMixin, enum.Enum):
    MANUAL = "manual"
    AUTO = "auto"
    SHUTTER = "shutter"
    FLICK50 = "flick50"
    FLICK60 = "flick60"


@enum.unique
class FocusMode(str, ValuesEnumMixin, enum.Enum):
    MANUAL = "manual"
    AUTO = "auto"
    ZTRIG = "ztrig"
    TOUCH = "touch"


@enum.unique
class MountPosition(str, ValuesEnumMixin, enum.Enum):
    CEILING = "ceiling"
    WALL = "wall"
    DESK = "desk"


@enum.unique
class GeofencingSetting(str, ValuesEnumMixin, enum.Enum):
    OFF = "off"
    ALL_AWAY = "allAway"


@enum.unique
class MotionAlgorithm(str, ValuesEnumMixin, enum.Enum):
    STABLE = "stable"
    ENHANCED = "enhanced"


@enum.unique
class AudioCodecs(str, ValuesEnumMixin, enum.Enum):
    AAC = "aac"
    VORBIS = "vorbis"
    OPUS = "opus"


@enum.unique
class LowMedHigh(str, ValuesEnumMixin, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@enum.unique
class StorageType(str, ValuesEnumMixin, enum.Enum):
    DISK = "hdd"
    RAID = "raid"
    SD_CARD = "sdcard"
    INTERNAL_SSD = "internalSSD"
    UNKNOWN = "UNKNOWN"


@enum.unique
class FirmwareReleaseChannel(str, ValuesEnumMixin, enum.Enum):
    INTERNAL = "internal"
    ALPHA = "alpha"
    BETA = "beta"
    RELEASE_CANDIDATE = "release-candidate"
    RELEASE = "release"


@enum.unique
class ChimeType(int, enum.Enum):
    NONE = 0
    MECHANICAL = 300
    DIGITAL = 1000


@enum.unique
class LockStatusType(str, ValuesEnumMixin, enum.Enum):
    OPEN = "OPEN"
    OPENING = "OPENING"
    CLOSED = "CLOSED"
    CLOSING = "CLOSING"
    JAMMED_WHILE_CLOSING = "JAMMED_WHILE_CLOSING"
    JAMMED_WHILE_OPENING = "JAMMED_WHILE_OPENING"
    FAILED_WHILE_CLOSING = "FAILED_WHILE_CLOSING"
    FAILED_WHILE_OPENING = "FAILED_WHILE_OPENING"
    NOT_CALIBRATED = "NOT_CALIBRATED"
    AUTO_CALIBRATION_IN_PROGRESS = "AUTO_CALIBRATION_IN_PROGRESS"
    CALIBRATION_WAITING_OPEN = "CALIBRATION_WAITING_OPEN"
    CALIBRATION_WAITING_CLOSE = "CALIBRATION_WAITING_CLOSE"


@enum.unique
class PermissionNode(str, enum.Enum):
    CREATE = "create"
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    READ_MEDIA = "readmedia"
    DELETE_MEDIA = "deletemedia"


@enum.unique
class LensType(str, enum.Enum):
    NONE = "none"
    FULL_360 = "360"
    WIDE = "wide"
    TELESCOPIC = "tele"


class DoorbellText(ConstrainedStr):
    max_length = 30


class LEDLevel(ConstrainedInt):
    ge = 0
    le = 6


class PercentInt(ConstrainedInt):
    ge = 0
    le = 100


class TwoByteInt(ConstrainedInt):
    ge = 1
    le = 255


class PercentFloat(ConstrainedFloat):
    ge = 0
    le = 100


class WDRLevel(ConstrainedInt):
    ge = 0
    le = 3


class ICRSensitivity(ConstrainedInt):
    ge = 0
    le = 3


class Percent(ConstrainedFloat):
    ge = 0
    le = 1


CoordType = Union[Percent, int, float]


class Color(BaseColor):
    def __eq__(self, o: Any) -> bool:
        if isinstance(o, Color):
            return self.as_hex() == o.as_hex()

        return super().__eq__(o)


class Version(BaseVersion):
    def __str__(self) -> str:
        super_str = super().__str__()
        if self.pre is not None and self.pre[0] == "b":
            super_str = super_str.replace("b", "-beta.")
        return super_str
