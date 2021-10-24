from datetime import timedelta
from typing import Any, Dict, Optional

from ..unifi_data import (
    CHIME_DISABLED,
    EVENT_LENGTH_PRECISION,
    EVENT_RING,
    LIVE_RING_FROM_WEBSOCKET,
    PRIVACY_ON,
    ZONE_NAME,
    EventType,
)
from ..utils import (
    format_datetime,
    from_js_time,
    is_doorbell,
    is_online,
    process_datetime,
)


def legacy_process_common(
    data: Dict[str, Any], server_id: Optional[str] = None, has_motion: bool = False
) -> Dict[str, Any]:
    """
    Method primarily used by tests to ensure output format is not broken for compatibility for
    processing all Protect devices
    """

    processed_data = {
        "name": str(data["name"]),
        "type": data["modelKey"],
        "model": str(data["type"]),
        "mac": str(data["mac"]),
        "ip_address": str(data["host"]),
        "firmware_version": str(data["firmwareVersion"]),
        "up_since": format_datetime(process_datetime(data, "upSince"), "Offline"),
        "online": is_online(data),
    }

    if has_motion:
        processed_data.update({"last_motion": format_datetime(process_datetime(data, "lastMotion"))})

    if server_id is not None:
        processed_data["server_id"] = server_id

    return processed_data


def legacy_process_viewport(data: Dict[str, Any], server_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Method primarily used by tests to ensure output format is not broken for compatibility for
    processing viewport Protect devices
    """

    processed_data = legacy_process_common(data, server_id=server_id, has_motion=False)

    processed_data.update(
        {
            "liveview": str(data["liveview"]),
        }
    )

    return processed_data


def legacy_process_light(data: Dict[str, Any], server_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Method primarily used by tests to ensure output format is not broken for compatibility for
    processing light Protect devices
    """

    processed_data = legacy_process_common(data, server_id=server_id, has_motion=True)

    light_mode_settings = data.get("lightModeSettings", {})
    device_settings = data.get("lightDeviceSettings", {})

    processed_data.update(
        {
            "motion_mode": light_mode_settings.get("mode"),
            "motion_mode_enabled_at": light_mode_settings.get("enableAt"),
            "is_on": data["isLightOn"],
            "brightness": int(device_settings.get("ledLevel")),
            "lux_sensitivity": device_settings.get("luxSensitivity"),
            "pir_duration": device_settings.get("pirDuration"),
            "pir_sensitivity": device_settings.get("pirSensitivity"),
            "status_light": device_settings.get("isIndicatorEnabled"),
        }
    )

    return processed_data


def legacy_process_camera(data: Dict[str, Any], host: str, server_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Method primarily used by tests to ensure output format is not broken for compatibility for
    processing camera Protect devices
    """

    processed_data = legacy_process_common(data, server_id=server_id, has_motion=True)

    feature_flags = data.get("featureFlags", {})

    privacy_on = False
    for row in data.get("privacyZones", []):
        if row["name"] == ZONE_NAME:
            privacy_on = row["points"] == PRIVACY_ON
            break

    rtsp = None
    image_width = None
    image_height = None
    stream_sources = []
    for channel in data["channels"]:
        if channel["isRtspEnabled"]:
            channel_width = channel.get("width")
            channel_height = channel.get("height")
            rtsp_url = f"rtsps://{host}:7441/{channel['rtspAlias']}?enableSrtp"

            # ensure image_width/image_height is not None
            if image_width is None:
                image_width = channel_width
                image_height = channel_height

            # Always Return the Highest Default Resolution
            # and make sure image_width/image_height comes from the same channel
            if rtsp is None:
                image_width = channel_width
                image_height = channel_height
                rtsp = rtsp_url

            stream_sources.append(
                {
                    "name": channel.get("name"),
                    "id": channel.get("id"),
                    "video_id": channel.get("videoId"),
                    "rtsp": rtsp_url,
                    "image_width": channel_width,
                    "image_height": channel_height,
                }
            )

    processed_data.update(
        {
            "last_ring": format_datetime(process_datetime(data, "lastRing")),
            "type": "doorbell" if is_doorbell(data) else "camera",
            "recording_mode": str(data["recordingSettings"]["mode"]),
            "ir_mode": str(data["ispSettings"]["irLedMode"]),
            "status_light": data["ledSettings"]["isEnabled"],
            "rtsp": rtsp,
            "image_width": image_width,
            "image_height": image_height,
            "has_highfps": "highFps" in feature_flags.get("videoModes", ""),
            "has_hdr": feature_flags.get("hasHdr"),
            "video_mode": data.get("videoMode") or "default",
            "hdr_mode": bool(data.get("hdrMode")),
            "mic_volume": data.get("micVolume") or 0,
            "has_smartdetect": feature_flags.get("hasSmartDetect"),
            "has_ledstatus": feature_flags.get("hasLedStatus"),
            "is_dark": bool(data.get("isDark")),
            "privacy_on": privacy_on,
            "has_opticalzoom": feature_flags.get("canOpticalZoom"),
            "zoom_position": str(data["ispSettings"]["zoomPosition"]),
            "wdr": str(data["ispSettings"]["wdr"]),
            "has_chime": feature_flags.get("hasChime"),
            "chime_enabled": data.get("chimeDuration") not in CHIME_DISABLED,
            "chime_duration": data.get("chimeDuration"),
            "stream_source": stream_sources,
        }
    )

    return processed_data


def round_event_duration(duration: timedelta) -> float:
    return round(duration.total_seconds(), EVENT_LENGTH_PRECISION)


def legacy_process_event(event: Dict[str, Any], minimum_score: int, ring_interval: int) -> Dict[str, Any]:
    """
    Method primarily used by tests to ensure output format is not broken for compatibility for
    processing events
    """

    start = process_datetime(event, "start")
    end = process_datetime(event, "end")
    event_type = event.get("type")
    score = event.get("score")

    duration = timedelta(seconds=0)
    if start and end:
        duration = end - start

    processed_event = {
        "event_on": False,
        "event_ring_on": False,
        "event_type": event_type,
        "event_start": format_datetime(start),
        "event_length": round_event_duration(duration),
        "event_score": score,
    }

    if smart_detect_types := event.get("smartDetectTypes"):
        processed_event["event_object"] = smart_detect_types
    elif not event.get("smartDetectEvents"):
        # Only clear the event_object if smartDetectEvents
        # is not set in the followup motion event
        processed_event["event_object"] = None

    if event_type in [EventType.MOTION.value, EventType.SMART_DETECT.value]:
        processed_event["last_motion"] = processed_event["event_start"]

        if score is not None and int(score) >= minimum_score and not end:
            processed_event["event_on"] = True
    elif event_type == EVENT_RING:
        processed_event["last_ring"] = processed_event["event_start"]

        ring_cuttoff = from_js_time(ring_interval)
        if ring_interval == LIVE_RING_FROM_WEBSOCKET or not end:
            processed_event["event_ring_on"] = True
        elif start and end and start >= ring_cuttoff and end >= ring_cuttoff:
            processed_event["event_ring_on"] = True

    thumbail = event.get("thumbnail")
    if thumbail is not None:  # Only update if there is a new Motion Event
        processed_event["event_thumbnail"] = thumbail

    heatmap = event.get("heatmap")
    if heatmap is not None:  # Only update if there is a new Motion Event
        processed_event["event_heatmap"] = heatmap

    return processed_event
