import enum

from pydantic import ConstrainedDecimal, ConstrainedInt


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
    CUSTOM_MESSAGE = "CUSTOM_MESSAGE"


@enum.unique
class LightModeEnableType(str, enum.Enum):
    DARK = "dark"
    ALWAYS = "fulltime"


@enum.unique
class LightModeType(str, enum.Enum):
    MOTION = "motion"
    WHEN_DARK = "always"
    MANUAL = "off"


@enum.unique
class VideoMode(str, enum.Enum):
    DEFAULT = "default"
    HIGH_FPS = "highFps"


@enum.unique
class RecordingMode(str, enum.Enum):
    ALWAYS = "always"
    NEVER = "never"
    MOTION_EVENTS = "motion"
    SMART_DETECTIONS = "smartDetect"


class LEDLevel(ConstrainedInt):
    ge = 1
    le = 6


class PercentInt(ConstrainedInt):
    ge = 0
    le = 100


class Percent(ConstrainedDecimal):
    ge = 0
    le = 1
    max_digits = 4
    decimal_places = 3
