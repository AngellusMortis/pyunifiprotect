import secrets
import string
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import uuid

import typer

from pyunifiprotect.data import ModelType

object_id_mapping: Dict[str, str] = {}


def anonymize_data(value: Any, name: Optional[str] = None) -> Any:
    if isinstance(value, list):
        value = anonymize_list(value, name=name)
    elif isinstance(value, dict):
        value = anonymize_dict(value, name=name)
    else:
        value = anonymize_value(value, name=name)

    return value


def anonymize_user(user_dict: Dict[str, Any]) -> Dict[str, Any]:
    for index, group_id in enumerate(user_dict.get("groups", [])):
        user_dict["groups"][index] = anonymize_object_id(group_id)

    user_dict["id"] = anonymize_object_id(user_dict["id"])

    if "firstName" in user_dict:
        user_dict["firstName"] = random_word().title()
        user_dict["lastName"] = random_word().title()
        user_dict["name"] = f"{user_dict['firstName']} {user_dict['lastName']}"
        user_dict["localUsername"] = random_word()
        user_dict["email"] = f"{user_dict['localUsername']}@example.com"

    if "cloudAccount" in user_dict and user_dict["cloudAccount"] is not None:
        user_dict["cloudAccount"]["firstName"] = user_dict["firstName"]
        user_dict["cloudAccount"]["lastName"] = user_dict["lastName"]
        user_dict["cloudAccount"]["name"] = user_dict["name"]
        user_dict["cloudAccount"]["email"] = user_dict["email"]
        user_dict["cloudAccount"]["user"] = anonymize_object_id(user_dict["cloudAccount"]["user"])
        user_dict["cloudAccount"]["id"] = anonymize_uuid(user_dict["cloudAccount"]["id"])
        user_dict["cloudAccount"]["cloudId"] = anonymize_uuid(user_dict["cloudAccount"]["cloudId"])

    camera_order = (user_dict.get("settings") or {}).get("cameraOrder")
    if camera_order is not None:
        for index, camera_id in enumerate(camera_order):
            camera_order[index] = anonymize_object_id(camera_id)
        user_dict["settings"]["cameraOrder"] = camera_order

    if "allPermissions" in user_dict:
        user_dict["allPermissions"] = anonymize_list(user_dict["allPermissions"], "allPermissions")
    if "permissions" in user_dict:
        user_dict["permissions"] = anonymize_list(user_dict["permissions"], "permissions")

    return user_dict


def anonymize_value(value: Any, name: Optional[str] = None) -> Any:
    if isinstance(value, str):
        if name == "accessKey":
            value = f"{random_number(13)}:{random_hex(24)}:{random_hex(128)}"
        elif name == "credentials":
            value = f"{random_hex(64)}"
        elif name == "privateToken":
            value = f"{random_alphanum(192)}"
        elif name in ("host", "connectionHost", "bindAddr"):
            value = anonymize_ip(value)
        elif name in ("anonymousDeviceId", "hardwareId"):
            value = random_identifier()
        elif name in ("rtspAlias", "ssid"):
            value = random_alphanum(16)
        elif name in ("mac", "server_id"):
            value = anonymize_peristent_string(value, random_hex(12).upper())
        elif name == "bssid":
            value = anonymize_peristent_string(value, random_seperated_mac())
        elif name in ("latitude", "longitude"):
            value = "0.0"
        elif name == "name" and value != "Default":
            value = f"{random_word()} {random_word()}".title()
        elif name in ("owner", "user", "camera", "liveview", "authUserId", "event"):
            value = anonymize_object_id(value)
        elif name == "rtsp":
            value = anonymize_rstp_url(value)
        elif value.startswith("liveview:*:"):
            liveview_id = value.split(":")[-1]
            value = f"liveview:*:{anonymize_object_id(liveview_id)}"

    return value


def anonymize_dict(obj: Dict[str, Any], name: Optional[str] = None) -> Dict[str, Any]:
    obj_type = None
    if "modelKey" in obj:
        if obj["modelKey"] in [m.value for m in ModelType]:
            obj_type = ModelType(obj["modelKey"])
        else:
            typer.secho(f"Unknown modelKey: {obj['modelKey']}", fg="yellow")

    if obj_type == ModelType.USER:
        return anonymize_user(obj)

    for key, value in obj.items():
        handled = False
        if obj_type is not None or "payload" in obj:
            if key == "id":
                obj[key] = anonymize_object_id(value)
                handled = True
            elif obj_type == ModelType.EVENT:
                if key in ("thumbnail", "heatmap"):
                    obj[key] = anonymize_prefixed_event_id(value)
                    handled = True
                elif key == "metadata":
                    if "sensorId" in obj[key]:
                        obj[key]["sensorId"]["text"] = anonymize_object_id(obj[key]["sensorId"]["text"])
                    if "sensorName" in obj[key]:
                        obj[key]["sensorName"]["text"] = f"{random_word()} {random_word()}".title()

        if not handled:
            obj[key] = anonymize_data(value, name=key)

    return obj


def anonymize_list(items: List[Any], name: Optional[str] = None) -> List[Any]:
    for index, value in enumerate(items):
        handled = False

        if isinstance(value, str) and name in ("hosts", "smartDetectEvents", "camera", "cameras"):
            handled = True
            if name == "hosts":
                items[index] = anonymize_ip(items[index])
            elif name == "smartDetectEvents":
                items[index] = anonymize_object_id(value)
            elif name in ("camera", "cameras"):
                items[index] = anonymize_object_id(value)

        if not handled:
            items[index] = anonymize_data(value)

    return items


def anonymize_prefixed_event_id(event_id: str) -> str:
    event_id = event_id[2:]

    return f"e-{anonymize_object_id(event_id)}"


def anonymize_ip(ip: Any) -> Any:
    if not isinstance(ip, str):
        return ip

    if ip in ("0.0.0.0", "127.0.0.1", "255.255.255.255"):
        return ip

    return anonymize_peristent_string(ip, random_ip(ip))


def anonymize_uuid(uuid_str: str) -> str:
    return anonymize_peristent_string(uuid_str, random_identifier())


def anonymize_object_id(obj_id: str) -> str:
    return anonymize_peristent_string(obj_id, random_hex(24))


def anonymize_peristent_string(value: str, default: str) -> str:
    if value not in object_id_mapping:
        object_id_mapping[value] = default

    return object_id_mapping[value]


def anonymize_rstp_url(url: str) -> str:
    parts = urlparse(url)
    port = ""
    if parts.port is not None and parts.port != 554:
        port = f":{parts.port}"

    return f"{parts.scheme}://{anonymize_ip(url)}{port}/{random_alphanum(16)}"


def random_hex(length: int) -> str:
    return secrets.token_hex(length // 2)


def random_seperated_mac() -> str:
    return ":".join(random_hex(2) for _ in range(6))


def random_str(length: int, choices: str) -> str:
    return "".join(secrets.choice(choices) for _ in range(length))


def random_number(length: int) -> str:
    return random_str(length, string.digits)


def random_word() -> str:
    return random_char(secrets.randbelow(5) + 3)


def random_char(length: int) -> str:
    return random_str(length, string.ascii_letters)


def random_alphanum(length: int) -> str:
    choices = string.ascii_letters + string.ascii_letters.upper() + string.digits
    return random_str(length, choices)


def random_ip(input_ip: str) -> str:
    ip = ""

    try:
        octals = [int(i) for i in input_ip.split(".")]
    except ValueError:
        pass
    else:
        if octals[0] == 10:
            ip = f"10.{secrets.randbelow(256)}.{secrets.randbelow(256)}.{secrets.randbelow(256)}"
        elif octals[0] == 172 and 16 <= octals[1] <= 31:
            ip = f"172.{secrets.randbelow(16) + 16}.{secrets.randbelow(256)}.{secrets.randbelow(256)}"
        elif octals[0] == 192 and octals[1] == 168:
            ip = f"192.168.{secrets.randbelow(256)}.{secrets.randbelow(256)}"

    if ip == "":
        ip = f"{secrets.randbelow(255) + 1}.{secrets.randbelow(256)}.{secrets.randbelow(256)}.{secrets.randbelow(256)}"
    return ip


def random_identifier() -> str:
    return str(uuid.uuid4())
