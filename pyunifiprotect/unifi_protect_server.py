"""Unifi Protect Server Wrapper."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import json as pjson
import logging
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional, Union
from urllib.parse import urljoin
from uuid import UUID

import aiohttp
from aiohttp import client_exceptions
import jwt
from yarl import URL

from pyunifiprotect.const import SERVER_ID, SERVER_NAME
from pyunifiprotect.data import (
    Event,
    EventType,
    ProtectWSPayloadFormat,
    WSPacket,
    create_from_unifi_dict,
)
from pyunifiprotect.data.bootstrap import Bootstrap
from pyunifiprotect.exceptions import BadRequest, NotAuthorized, NvrError
from pyunifiprotect.unifi_data import (
    DEVICE_MODEL_LIGHT,
    EVENT_MOTION,
    EVENT_RING,
    EVENT_SMART_DETECT_ZONE,
    PRIVACY_OFF,
    PRIVACY_ON,
    PROCESSED_EVENT_EMPTY,
    TYPE_RECORD_NEVER,
    ZONE_NAME,
    ProtectDeviceStateMachine,
    ProtectEventStateMachine,
    camera_event_from_ws_frames,
    camera_update_from_ws_frames,
    decode_ws_frame,
    event_from_ws_frames,
    light_event_from_ws_frames,
    light_update_from_ws_frames,
    process_camera,
    process_event,
    process_light,
    process_sensor,
    process_viewport,
    sensor_event_from_ws_frames,
    sensor_update_from_ws_frames,
)
from pyunifiprotect.utils import get_response_reason, set_debug, to_js_time

NEVER_RAN = -1000
# how many seconds before the bootstrap is refreshed from Protect
DEVICE_UPDATE_INTERVAL = 60
# how many seconds before before we check for an active WS connection
WEBSOCKET_CHECK_INTERVAL = 120
LIGHT_MODES = ["off", "motion", "always"]
LIGHT_ENABLED = ["dark", "fulltime"]
LIGHT_DURATIONS = [15000, 30000, 60000, 300000, 900000]

DEFAULT_SNAPSHOT_WIDTH = 1920
DEFAULT_SNAPSHOT_HEIGHT = 1080


_LOGGER = logging.getLogger(__name__)


# TODO: Remove when 3.8 support is dropped
if TYPE_CHECKING:
    TaskClass = asyncio.Task[None]
else:
    TaskClass = asyncio.Task


class BaseApiClient:
    _host: str
    _port: int
    _base_url: str
    _username: str
    _password: str
    _verify_ssl: bool
    _is_authenticated: bool = False
    _last_update: float = NEVER_RAN
    _last_websocket_check: float = NEVER_RAN

    req: aiohttp.ClientSession
    headers: Optional[Dict[str, str]] = None
    last_update_id: Optional[UUID] = None
    ws_session: Optional[aiohttp.ClientSession] = None
    ws_connection: Optional[aiohttp.ClientWebSocketResponse] = None
    ws_task: Optional[TaskClass] = None
    ws_callback: Optional[Callable[[aiohttp.WSMessage], None]] = None

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        verify_ssl: bool = True,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        self._host = host
        self._port = port
        self._base_url = f"https://{host}:{port}"
        self._base_ws_url = f"wss://{host}:{port}"
        self._username = username
        self._password = password
        self._verify_ssl = verify_ssl

        if session is None:
            session = aiohttp.ClientSession()

        self.req = session

    @property
    def api_path(self) -> str:
        return "/proxy/protect/api/"

    @property
    def ws_path(self) -> str:
        return "/proxy/protect/ws/"

    async def request(
        self, method: str, url: str, require_auth: bool = False, auto_close: bool = True, **kwargs: Any
    ) -> aiohttp.ClientResponse:
        """Make a request to Unifi Protect"""

        if require_auth:
            await self.ensure_authenticated()

        url = urljoin(self._base_url, url)
        headers = kwargs.get("headers") or self.headers

        _LOGGER.debug("Request url: %s", url)

        try:
            req_context = self.req.request(method, url, ssl=self._verify_ssl, headers=headers, **kwargs)
            response = await req_context.__aenter__()

            try:
                _LOGGER.debug("%s %s %s", response.status, response.content_type, response)

                if response.status in (401, 403):
                    raise NotAuthorized(
                        f"Unifi Protect reported authorization failure on request: {url} received {response.status}"
                    )

                if response.status == 404:
                    raise NvrError(f"Call {url} received 404 Not Found")

                if auto_close:
                    response.release()

                return response
            except Exception:
                # make sure response is released
                response.release()
                # re-raise exception
                raise

        except client_exceptions.ClientError as err:
            raise NvrError(f"Error requesting data from {self._host}: {err}") from None

    async def api_request_raw(
        self,
        url: str,
        method: str = "get",
        require_auth: bool = True,
        raise_exception: bool = True,
        **kwargs: Any,
    ) -> Optional[bytes]:
        """Make a request to Unifi Protect API"""

        if require_auth:
            await self.ensure_authenticated()

        url = urljoin(self.api_path, url)
        response = await self.request(method, url, require_auth=False, auto_close=False, **kwargs)

        try:
            if response.status != 200:
                reason = await get_response_reason(response)
                msg = "Request failed: %s - Status: %s - Reason: %s"
                if raise_exception:
                    raise NvrError(msg % (url, response.status, reason))
                _LOGGER.warning(msg, url, response.status, reason)
                return None

            data: Optional[bytes] = await response.read()
            response.release()

            return data
        except Exception:
            # make sure response is released
            response.release()
            # re-raise exception
            raise

    async def api_request(
        self,
        url: str,
        method: str = "get",
        require_auth: bool = True,
        raise_exception: bool = True,
        **kwargs: Any,
    ) -> Optional[Union[List[Any], Dict[str, Any]]]:
        data = await self.api_request_raw(
            url=url, method=method, require_auth=require_auth, raise_exception=raise_exception, **kwargs
        )

        if data is not None:
            json_data: Union[List[Any], Dict[str, Any]] = pjson.loads(data)
            return json_data
        return None

    async def api_request_obj(
        self,
        url: str,
        method: str = "get",
        require_auth: bool = True,
        raise_exception: bool = True,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        data = await self.api_request(
            url=url, method=method, require_auth=require_auth, raise_exception=raise_exception, **kwargs
        )

        if not isinstance(data, dict):
            raise NvrError(f"Could not decode object from {url}")

        return data

    async def api_request_list(
        self,
        url: str,
        method: str = "get",
        require_auth: bool = True,
        raise_exception: bool = True,
        **kwargs: Any,
    ) -> List[Any]:
        data = await self.api_request(
            url=url, method=method, require_auth=require_auth, raise_exception=raise_exception, **kwargs
        )

        if not isinstance(data, list):
            raise NvrError(f"Could not decode list from {url}")

        return data

    async def ensure_authenticated(self) -> None:
        """Ensure we are authenticated."""
        if self.is_authenticated() is False:
            await self.authenticate()

    async def authenticate(self) -> None:
        """Authenticate and get a token."""

        url = "/api/auth/login"
        self.req.cookie_jar.clear()

        auth = {
            "username": self._username,
            "password": self._password,
            "remember": True,
        }

        response = await self.request("post", url=url, json=auth)
        self.headers = {
            "cookie": response.headers.get("set-cookie", ""),
        }

        csrf_token = response.headers.get("x-csrf-token")
        if csrf_token is not None:
            self.headers["x-csrf-token"] = csrf_token

        self._is_authenticated = True
        _LOGGER.debug("Authenticated successfully!")

    def is_authenticated(self) -> bool:
        """Check to see if we are already authenticated."""
        if self._is_authenticated is True:
            # Check if token is expired.
            cookies = self.req.cookie_jar.filter_cookies(URL(self._base_url))
            token_cookie = cookies.get("TOKEN")
            if token_cookie is None:
                return False
            try:
                jwt.decode(
                    token_cookie.value,
                    options={"verify_signature": False, "verify_exp": True},
                )
            except jwt.ExpiredSignatureError:
                _LOGGER.debug("Authentication token has expired.")
                return False
            except Exception as broad_ex:  # pylint: disable=broad-except
                _LOGGER.debug("Authentication token decode error: %s", broad_ex)
                return False

        return self._is_authenticated

    def disconnect_ws(self) -> None:
        """Disconnects from the websocket if already connected."""
        if self.ws_connection is not None:
            return

        if self.ws_task is not None:
            try:
                self.ws_task.cancel()
                self.ws_connection = None
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Could not cancel ws_task")

    async def async_connect_ws(self) -> None:
        """Connect the websocket."""
        if self.ws_connection is not None:
            return

        self.disconnect_ws()
        self.ws_task = asyncio.ensure_future(self._setup_websocket())

    async def async_disconnect_ws(self) -> None:
        """Disconnect the websocket."""
        if self.ws_connection is None:
            return

        await self.ws_connection.close()
        if self.ws_session is not None:
            await self.ws_session.close()

    async def _setup_websocket(self) -> None:
        await self.ensure_authenticated()

        url = urljoin(f"{self._base_ws_url}{self.ws_path}", "updates")
        if self.last_update_id:
            url += f"?lastUpdateId={self.last_update_id}"

        if not self.ws_session:
            self.ws_session = aiohttp.ClientSession()
        _LOGGER.debug("WS connecting to: %s", url)

        self.ws_connection = await self.ws_session.ws_connect(url, ssl=self._verify_ssl, headers=self.headers)
        try:
            async for msg in self.ws_connection:
                if self.ws_callback is not None:
                    self.ws_callback(msg)  # pylint: disable=not-callable

                if msg.type == aiohttp.WSMsgType.BINARY:
                    try:
                        self._process_ws_message(msg)
                    except Exception:  # pylint: disable=broad-except
                        _LOGGER.exception("Error processing websocket message")
                        return
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.exception("Error from Websocket: %s", msg.data)
                    break
        finally:
            _LOGGER.debug("websocket disconnected")
            self.ws_connection = None

    async def check_ws(self) -> bool:
        now = time.monotonic()

        first_check = self._last_websocket_check == NEVER_RAN
        connect_ws = False
        if now - self._last_websocket_check > WEBSOCKET_CHECK_INTERVAL:
            _LOGGER.debug("Checking websocket")
            self._last_websocket_check = now
            connect_ws = True
            await self.async_connect_ws()

        # log if no active WS
        if not self.ws_connection and not first_check:
            log = _LOGGER.debug
            # but only warn if a reconnect attempt was made
            if connect_ws:
                log = _LOGGER.warning
            log("Unifi OS: Websocket connection not active, failing back to polling")

        if self.ws_connection or self._last_websocket_check == now:
            return True
        return False

    def _process_ws_message(self, msg: aiohttp.WSMessage) -> None:
        raise NotImplementedError()


class UpvServer(BaseApiClient):  # pylint: disable=too-many-public-methods, too-many-instance-attributes
    """Updates device States and Attributes."""

    _minimum_score: int

    _event_state_machine: ProtectEventStateMachine = ProtectEventStateMachine()
    _device_state_machine: ProtectDeviceStateMachine = ProtectDeviceStateMachine()
    _processed_data: Dict[str, Dict[str, Any]] = {}
    _last_device_update_time: float = NEVER_RAN
    _ws_subscriptions: List[Callable[[Dict[str, Dict[str, Any]]], None]] = []
    _is_first_update: bool = True

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession],
        host: str,
        port: int,
        username: str,
        password: str,
        verify_ssl: bool = False,
        minimum_score: int = 0,
    ) -> None:
        super().__init__(host, port, username, password, verify_ssl, session=session)

        self._minimum_score = minimum_score

    @property
    def devices(self) -> Dict[str, Dict[str, Any]]:
        """Returns a JSON formatted list of Devices."""
        return self._processed_data

    async def update(self, force_camera_update: bool = False) -> Dict[str, Any]:
        """Updates the status of devices."""

        now = time.monotonic()
        if force_camera_update and self.ws_connection is not None:
            self._last_update = NEVER_RAN
            self._last_websocket_check = NEVER_RAN

        device_update = False
        if now - self._last_update > DEVICE_UPDATE_INTERVAL:
            _LOGGER.debug("Doing device update")
            device_update = True
            await self._get_device_list(not self.ws_connection)
            self._last_update = now
        else:
            _LOGGER.debug("Skipping device update")

        active_ws = await self.check_ws()
        # If the websocket is connected/connecting
        # we do not need to get events
        if active_ws:
            _LOGGER.debug("Skipping update since websocket is active")
            return self._processed_data if device_update else {}

        self._reset_device_events()
        updates = await self._get_events(lookback=10)

        return self._processed_data if device_update else updates

    async def server_information(self) -> Dict[str, Any]:
        """Returns a Server Information for this NVR."""
        return await self._get_server_info()

    async def _get_unique_id(self) -> str:
        """Get a Unique ID for this NVR."""

        server_id: str = (await self._get_server_info())[SERVER_ID]
        return server_id

    async def _get_server_info(self) -> Dict[str, Any]:
        """Get Server Information for this NVR."""

        data = await self.api_request_obj("bootstrap")
        nvr_data: Dict[str, Any] = data["nvr"]

        return {
            SERVER_NAME: nvr_data["name"],
            "server_version": nvr_data["version"],
            SERVER_ID: nvr_data["mac"],
            "server_model": nvr_data["type"],
            "server_ip": nvr_data["host"],
        }

    async def _get_device_list(self, include_events: bool) -> None:
        """Get a list of devices connected to the NVR."""

        data = await self.api_request_obj("bootstrap")
        server_id: str = data["nvr"]["mac"]
        if not self.ws_connection and "lastUpdateId" in data:
            self.last_update_id = UUID(data["lastUpdateId"])

        self._process_cameras_json(data, server_id, include_events)
        self._process_lights_json(data, server_id, include_events)
        self._process_sensors_json(data, server_id, include_events)
        self._process_viewports_json(data, server_id, include_events)

        self._is_first_update = False

    def _process_cameras_json(self, json_response: Dict[str, Any], server_id: str, include_events: bool) -> None:
        for camera in json_response["cameras"]:

            # Ignore cameras adopted by another controller on the same network
            # since they appear in the api on 1.17+
            if "isAdopted" in camera and not camera["isAdopted"]:
                continue

            camera_id = camera["id"]

            if self._is_first_update:
                self._update_device(camera_id, PROCESSED_EVENT_EMPTY)
            self._device_state_machine.update(camera_id, camera)
            self._update_device(
                camera_id,
                process_camera(
                    server_id,
                    self._host,
                    camera,
                    include_events or self._is_first_update,
                ),
            )

    def _process_lights_json(self, json_response: Dict[str, Any], server_id: str, include_events: bool) -> None:
        for light in json_response["lights"]:

            # Ignore lights adopted by another controller on the same network
            # since they appear in the api on 1.17+
            if "isAdopted" in light and not light["isAdopted"]:
                continue

            light_id = light["id"]

            if self._is_first_update:
                self._update_device(light_id, PROCESSED_EVENT_EMPTY)
            self._device_state_machine.update(light_id, light)

            self._update_device(
                light_id,
                process_light(server_id, light, include_events or self._is_first_update),
            )

    def _process_sensors_json(self, json_response: Dict[str, Any], server_id: str, include_events: bool) -> None:
        for sensor in json_response["sensors"]:

            # Ignore sensors adopted by another controller on the same network
            # since they appear in the api on 1.17+
            if "isAdopted" in sensor and not sensor["isAdopted"]:
                continue

            sensor_id = sensor["id"]

            if self._is_first_update:
                self._update_device(sensor_id, PROCESSED_EVENT_EMPTY)
            self._device_state_machine.update(sensor_id, sensor)

            self._update_device(
                sensor_id,
                process_sensor(server_id, sensor, include_events or self._is_first_update),
            )

    def _process_viewports_json(self, json_response: Dict[str, Any], server_id: str, include_events: bool) -> None:
        for viewport in json_response["viewers"]:

            # Ignore viewports adopted by another controller on the same network
            # since they appear in the api on 1.17+
            if "isAdopted" in viewport and not viewport["isAdopted"]:
                continue

            viewport_id = viewport["id"]

            if self._is_first_update:
                self._update_device(viewport_id, PROCESSED_EVENT_EMPTY)
            self._device_state_machine.update(viewport_id, viewport)

            self._update_device(
                viewport_id,
                process_viewport(server_id, viewport, include_events or self._is_first_update),
            )

    def _reset_device_events(self) -> None:
        """Reset device events between device updates."""
        for device_id in self._processed_data:
            self._update_device(device_id, PROCESSED_EVENT_EMPTY)

    def _process_events(self, events: List[Dict[str, Any]], ring_interval: int) -> Dict[str, Any]:
        updated = {}
        for event in events:
            if event["type"] not in (EVENT_MOTION, EVENT_RING, EVENT_SMART_DETECT_ZONE):
                continue

            camera_id = event["camera"]
            self._update_device(
                camera_id,
                process_event(event, self._minimum_score, ring_interval),
            )
            updated[camera_id] = self._processed_data[camera_id]

        return updated

    async def _get_events(
        self,
        lookback: int = 86400,
        camera: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Load the Event Log and loop through items to find motion events."""

        now = int(time.time() * 1000)
        if start_time is None:
            start_time = now - (lookback * 1000)
        if end_time is None:
            end_time = now + 10000
        event_ring_check_converted = now - 3000

        params = {
            "end": str(end_time),
            "start": str(start_time),
        }
        if camera:
            params["cameras"] = camera
        data = await self.api_request("events", params=params)

        if not isinstance(data, list):
            raise NvrError("Could not decode events")

        return self._process_events(data, event_ring_check_converted)

    async def get_raw_events(self, lookback: int = 86400) -> List[Any]:
        """Load the Event Log and return the Raw Data - Used for debugging only."""

        event_start = datetime.now() - timedelta(seconds=lookback)
        event_end = datetime.now() + timedelta(seconds=10)
        start_time = int(time.mktime(event_start.timetuple())) * 1000
        end_time = int(time.mktime(event_end.timetuple())) * 1000

        params = {
            "end": str(end_time),
            "start": str(start_time),
        }

        return await self.api_request_list("events", params=params)

    async def get_raw_device_info(self) -> Dict[str, Any]:
        """Return the RAW JSON data from this NVR.
        Used for debugging purposes only.
        """

        return await self.api_request_obj("bootstrap")

    async def get_thumbnail(self, camera_id: str, width: int = 640) -> Optional[bytes]:
        """Returns the last recorded Thumbnail, based on Camera ID."""

        await self._get_events(camera=camera_id)

        thumbnail_id = self._processed_data[camera_id]["event_thumbnail"]
        if thumbnail_id is None:
            return None

        height = float(width) / 16 * 9
        params = {
            "h": str(height),
            "w": str(width),
        }
        return await self.api_request_raw(f"thumbnails/{thumbnail_id}", params=params)

    async def get_heatmap(self, camera_id: str) -> Optional[bytes]:
        """Returns the last recorded Heatmap, based on Camera ID."""

        await self._get_events(camera=camera_id)

        heatmap_id = self._processed_data[camera_id]["event_heatmap"]
        if heatmap_id is None:
            return None

        return await self.api_request_raw(f"heatmaps/{heatmap_id}")

    async def get_snapshot_image(
        self, camera_id: str, width: Optional[int] = None, height: Optional[int] = None
    ) -> Optional[bytes]:
        """Returns a Snapshot image of a recording event."""

        time_since = int(time.mktime(datetime.now().timetuple())) * 1000
        cam = self._processed_data[camera_id]
        image_width = width or cam.get("image_width") or DEFAULT_SNAPSHOT_WIDTH
        image_height = height or cam.get("image_height") or DEFAULT_SNAPSHOT_HEIGHT

        params = {
            "h": image_height,
            "ts": str(time_since),
            "force": "true",
            "w": image_width,
        }
        return await self.api_request_raw(f"cameras/{camera_id}/snapshot", params=params, raise_exception=False)

    async def get_snapshot_image_direct(self, camera_id: str) -> bytes:
        """Returns a Snapshot image of a recording event.
        This function will only work if Anonymous Snapshots
        are enabled on the Camera.
        """
        ip_address = self._processed_data[camera_id]["ip_address"]

        img_uri = f"http://{ip_address}/snap.jpeg"
        async with self.req.get(img_uri) as response:
            if response.status == 200:
                return await response.read()
            raise NvrError(f"Direct Snapshot failed: {response.status} - Reason: {response.reason}")

    async def set_camera_recording(self, camera_id: str, mode: str) -> bool:
        """Sets the camera recoding mode to what is supplied with 'mode'.
        Valid inputs for mode: never, detections and always
        """

        data = {
            "recordingSettings": {
                "mode": mode,
            }
        }
        await self.api_request(f"cameras/{camera_id}", method="patch", json=data)
        self._processed_data[camera_id]["recording_mode"] = mode
        return True

    async def set_camera_ir(self, camera_id: str, mode: str) -> bool:
        """Sets the camera infrared settings to what is supplied with 'mode'.
        Valid inputs for mode: auto, on, autoFilterOnly, off
        """

        data = {"ispSettings": {"irLedMode": mode}}
        await self.api_request(f"cameras/{camera_id}", method="patch", json=data)
        self._processed_data[camera_id]["ir_mode"] = mode
        return True

    async def set_device_status_light(self, device_id: str, mode: bool, device_model: str) -> bool:
        """Sets the device status light settings to what is supplied with 'mode'.
        Valid inputs for mode: False and True
        """

        if device_model == DEVICE_MODEL_LIGHT:
            uri = f"lights/{device_id}"
            data: Dict[str, Dict[str, Any]] = {"lightDeviceSettings": {"isIndicatorEnabled": mode}}
        else:
            uri = f"cameras/{device_id}"
            data = {"ledSettings": {"isEnabled": mode, "blinkRate": 0}}

        await self.api_request(uri, method="patch", json=data)
        self._processed_data[device_id]["status_light"] = mode
        return True

    async def set_camera_hdr_mode(self, camera_id: str, mode: bool) -> bool:
        """Sets the camera HDR mode to what is supplied with 'mode'.
        Valid inputs for mode: False and True
        """

        data = {"hdrMode": mode}
        await self.api_request(f"cameras/{camera_id}", method="patch", json=data)
        self._device_state_machine.update(camera_id, data)
        self._processed_data[camera_id]["hdr_mode"] = mode
        return True

    async def set_doorbell_chime_duration(self, camera_id: str, duration: int) -> bool:
        """Sets the Doorbells chime duration.
        Valid inputs for duration: 0 to 10000
        """

        if duration < 0:
            chime_duration = 0
        elif duration > 10000:
            chime_duration = 10000
        else:
            chime_duration = duration

        data = {"chimeDuration": chime_duration}
        await self.api_request(f"cameras/{camera_id}", method="patch", json=data)
        self._device_state_machine.update(camera_id, data)
        self._processed_data[camera_id]["chime_duration"] = chime_duration
        return True

    async def set_camera_video_mode_highfps(self, camera_id: str, mode: bool) -> bool:
        """Sets the camera High FPS video mode to what is supplied with 'mode'.
        Valid inputs for mode: False and True
        """

        highfps = "highFps" if mode is True else "default"

        data = {"videoMode": highfps}
        await self.api_request(f"cameras/{camera_id}", method="patch", json=data)
        self._device_state_machine.update(camera_id, data)
        self._processed_data[camera_id]["video_mode"] = highfps
        return True

    async def set_camera_zoom_position(self, camera_id: str, position: int) -> bool:
        """Sets the cameras optical zoom position.
        Valid inputs for position: Integer from 0 to 100
        """
        if position < 0:
            position = 0
        elif position > 100:
            position = 100

        data = {"ispSettings": {"zoomPosition": position}}
        await self.api_request(f"cameras/{camera_id}", method="patch", json=data)
        self._processed_data[camera_id]["zoom_position"] = position
        return True

    async def set_camera_wdr(self, camera_id: str, value: int) -> bool:
        """Sets the cameras Wide Dynamic Range.
        Valid inputs for position: Integer from 0 to 3
        """
        if value < 0:
            value = 0
        elif value > 3:
            value = 3

        data = {"ispSettings": {"wdr": value}}
        await self.api_request(f"cameras/{camera_id}", method="patch", json=data)
        self._processed_data[camera_id]["wdr"] = value
        return True

    async def set_mic_volume(self, camera_id: str, level: int) -> bool:
        """Sets the camera microphone volume level.
        Valid inputs is an integer between 0 and 100.
        """

        if level < 0:
            level = 0
        elif level > 100:
            level = 100

        data = {"micVolume": level}
        await self.api_request(f"cameras/{camera_id}", method="patch", json=data)
        self._device_state_machine.update(camera_id, data)
        self._processed_data[camera_id]["mic_volume"] = level
        return True

    async def set_light_on_off(self, light_id: str, turn_on: bool, led_level: Optional[int] = None) -> bool:
        """Sets the light on or off.
        turn_on can be: true or false.
        led_level: must be between 1 and 6 or None
        """

        data: Dict[str, Any] = {"lightOnSettings": {"isLedForceOn": turn_on}}
        if led_level is not None:
            data["lightDeviceSettings"] = {"ledLevel": led_level}

        await self.api_request(f"lights/{light_id}", method="patch", json=data)
        self._device_state_machine.update(light_id, data)
        processed_light = self._processed_data[light_id]
        processed_light["is_on"] = turn_on
        if led_level is not None:
            processed_light["brightness"] = led_level
        return True

    async def light_settings(
        self,
        light_id: str,
        mode: str,
        enable_at: Optional[Literal["dark", "fulltime"]] = None,
        duration: Optional[int] = None,
        sensitivity: Optional[int] = None,
    ) -> bool:
        """Sets PIR settings for a Light Device.
        mode can be: off, motion or always
        enableAt can be: dark, fulltime
        pirDuration: A number between 15000 and 900000 (ms)
        pirSensitivity: A number between 0 and 100
        """
        await self.ensure_authenticated()

        if mode not in LIGHT_MODES:
            mode = "motion"

        data: Dict[str, Any] = {"lightModeSettings": {"mode": mode}}
        if enable_at is not None:
            setting: Dict[str, Any] = data["lightModeSettings"]
            setting["enableAt"] = enable_at
        if duration is not None:
            if data.get("lightDeviceSettings"):
                setting = data["lightDeviceSettings"]
                setting["pirDuration"] = duration
            else:
                data["lightDeviceSettings"] = {"pirDuration": duration}
        if sensitivity is not None:
            if data.get("lightDeviceSettings"):
                setting = data["lightDeviceSettings"]
                setting["pirSensitivity"] = sensitivity
            else:
                data["lightDeviceSettings"] = {"pirSensitivity": sensitivity}

        await self.api_request(f"lights/{light_id}", method="patch", json=data)
        self._device_state_machine.update(light_id, data)
        processed_light = self._processed_data[light_id]
        processed_light["motion_mode"] = mode
        if enable_at is not None:
            processed_light["motion_mode_enabled_at"] = enable_at
        if duration is not None:
            processed_light["pir_duration"] = duration
        if sensitivity is not None:
            processed_light["pir_sensitivity"] = sensitivity
        return True

    async def set_privacy_mode(
        self, camera_id: str, mode: bool, mic_level: int = -1, recording_mode: str = "notset"
    ) -> bool:
        """Sets the camera privacy mode.
        When True, creates a privacy zone that fills the camera
        When False, removes the Privacy Zone
        Valid inputs for mode: False and True
        """

        # Set Microphone Level if needed
        if mic_level >= 0:
            await self.set_mic_volume(camera_id, mic_level)

        # Set recording mode if needed
        if recording_mode != "notset":
            await self.set_camera_recording(camera_id, recording_mode)

        # Set Privacy Mask
        if mode:
            privacy_value = PRIVACY_ON
        else:
            privacy_value = PRIVACY_OFF

        # We need the current camera setup
        caminfo = await self._get_camera_detail(camera_id)
        privdata = caminfo["privacyZones"]
        zone_exist = False
        items = []

        # Update Zone Information
        for row in privdata:
            if row["name"] == ZONE_NAME:
                row["points"] = privacy_value
                zone_exist = True
            items.append(row)
        if len(items) == 0 or not zone_exist:
            items.append({"name": "hass zone", "color": "#85BCEC", "points": privacy_value})

        # Update the Privacy Mode
        data = {"privacyZones": items}
        await self.api_request(f"cameras/{camera_id}", method="patch", json=data)
        self._processed_data[camera_id]["privacy_on"] = mode
        return True

    async def _get_camera_detail(self, camera_id: str) -> Dict[str, Any]:
        """Return the RAW JSON data for Camera.
        Used for debugging only.
        """

        return await self.api_request_obj(f"cameras/{camera_id}")

    async def _get_viewport_detail(self, viewport_id: str) -> Dict[str, Any]:
        """Return the RAW JSON data for a Viewport.
        Used for debugging only.
        """

        return await self.api_request_obj(f"viewers/{viewport_id}")

    async def _get_light_detail(self, light_id: str) -> Dict[str, Any]:
        """Return the RAW JSON data for a Light.
        Used for debugging only.
        """

        return await self.api_request_obj(f"lights/{light_id}")

    async def set_doorbell_lcd_text(
        self, camera_id: str, text_type: str, text_display: str, duration: Optional[int] = None
    ) -> bool:
        """Sets a Text string for the Doorbell LCD'."""

        # Truncate text to max 30 characters, as this is what is supported
        text_display = text_display[:30]

        # Calculate ResetAt time
        if duration is not None:
            now = datetime.now()
            now_plus_duration = now + timedelta(minutes=int(duration))
            duration = int(now_plus_duration.timestamp() * 1000)

        # resetAt is Unix timestamp in the future
        data = {
            "lcdMessage": {
                "type": text_type,
                "text": text_display,
                "resetAt": duration,
            }
        }
        await self.api_request(f"cameras/{camera_id}", method="patch", json=data)
        return True

    async def set_viewport_view(self, viewport_id: str, view_id: str) -> bool:
        """Sets the Viewport current View to what is supplied in view_id.
        Valid input for view_id is a pre-defined view in Protect.
        """

        data = {"liveview": view_id}
        await self.api_request(f"viewers/{viewport_id}", method="patch", json=data)

        self._device_state_machine.update(viewport_id, data)
        processed_viewport = self._processed_data[viewport_id]
        processed_viewport["liveview"] = view_id
        return True

    async def get_live_views(self) -> List[Dict[str, Dict[str, Any]]]:
        """Returns a list of all defined Live Views."""

        liveviews = await self.api_request_list("liveviews")

        views = []
        for view in liveviews:
            item = {
                "name": view.get("name"),
                "id": view.get("id"),
            }
            views.append(item)
        return views

    def subscribe_websocket(self, ws_callback: Callable[[Dict[str, Dict[str, Any]]], None]) -> Callable[[], None]:
        """Subscribe to websocket events.

        Returns a callback that will unsubscribe.
        """

        def _unsub_ws_callback() -> None:
            self._ws_subscriptions.remove(ws_callback)

        _LOGGER.debug("Adding subscription: %s", ws_callback)
        self._ws_subscriptions.append(ws_callback)
        return _unsub_ws_callback

    def _process_ws_message(self, msg: aiohttp.WSMessage) -> None:
        """Process websocket messages."""
        action_frame, action_frame_payload_format, position = decode_ws_frame(msg.data, 0)

        if action_frame_payload_format != ProtectWSPayloadFormat.JSON:
            return

        action_json = pjson.loads(action_frame)

        if action_json.get("action") not in (
            "add",
            "update",
        ):
            return

        model_key = action_json.get("modelKey")

        if model_key not in ("event", "camera", "light", "sensor"):
            return

        _LOGGER.debug("Action Frame: %s", action_json)

        data_frame, data_frame_payload_format, _ = decode_ws_frame(msg.data, position)

        if data_frame_payload_format != ProtectWSPayloadFormat.JSON:
            return

        data_json = pjson.loads(data_frame)
        _LOGGER.debug("Data Frame: %s", data_json)

        if model_key == "event":
            self._process_event_ws_message(action_json, data_json)
            return

        if model_key == "camera":
            self._process_camera_ws_message(action_json, data_json)
            return

        if model_key == "light":
            self._process_light_ws_message(action_json, data_json)
            return

        if model_key == "sensor":
            self._process_sensor_ws_message(action_json, data_json)
            return

        raise ValueError(f"Unexpected model key: {model_key}")

    def _process_camera_ws_message(self, action_json: Dict[str, Any], data_json: Dict[str, Any]) -> None:
        """Process a decoded camera websocket message."""
        camera_id, processed_camera = camera_update_from_ws_frames(
            self._device_state_machine, self._host, action_json, data_json
        )

        if camera_id is None or processed_camera is None:
            return
        _LOGGER.debug("Processed camera: %s", processed_camera)

        if processed_camera["recording_mode"] == TYPE_RECORD_NEVER:
            processed_event = camera_event_from_ws_frames(self._device_state_machine, action_json, data_json)
            if processed_event is not None:
                _LOGGER.debug("Processed camera event: %s", processed_event)
                processed_camera.update(processed_event)

        self.fire_event(camera_id, processed_camera)

    def _process_light_ws_message(self, action_json: Dict[str, Any], data_json: Dict[str, Any]) -> None:
        """Process a decoded light websocket message."""
        light_id, processed_light = light_update_from_ws_frames(self._device_state_machine, action_json, data_json)

        if light_id is None or processed_light is None:
            return
        _LOGGER.debug("Processed light: %s %s", processed_light["motion_mode"], processed_light)

        # Lights behave differently than Cameras so no check for recording state
        processed_event = light_event_from_ws_frames(self._device_state_machine, action_json, data_json)
        if processed_event is not None:
            _LOGGER.debug("Processed light event: %s", processed_event)
            processed_light.update(processed_event)

        self.fire_event(light_id, processed_light)

    def _process_sensor_ws_message(self, action_json: Dict[str, Any], data_json: Dict[str, Any]) -> None:
        """Process a decoded sensor websocket message."""
        sensor_id, processed_sensor = sensor_update_from_ws_frames(self._device_state_machine, action_json, data_json)

        if sensor_id is None or processed_sensor is None:
            return
        _LOGGER.debug(
            "Processed sensor: %s %s",
            processed_sensor["motion_enabled"],
            processed_sensor,
        )

        # Sensors behave differently than Cameras so no check for recording state
        processed_event = sensor_event_from_ws_frames(self._device_state_machine, action_json, data_json)
        if processed_event is not None:
            _LOGGER.debug("Processed sensor event: %s", processed_event)
            processed_sensor.update(processed_event)

        self.fire_event(sensor_id, processed_sensor)

    def _process_event_ws_message(self, action_json: Dict[str, Any], data_json: Dict[str, Any]) -> None:
        """Process a decoded event websocket message."""
        device_id, processed_event = event_from_ws_frames(
            self._event_state_machine, self._minimum_score, action_json, data_json
        )

        if device_id is None or processed_event is None:
            return

        _LOGGER.debug("Procesed event: %s", processed_event)

        self.fire_event(device_id, processed_event)

        if processed_event["event_ring_on"]:
            # The websocket will not send any more events since
            # doorbell rings do not have a length. We fire an
            # additional event to turn off the ring.
            processed_event["event_ring_on"] = False
            self.fire_event(device_id, processed_event)

    def fire_event(self, device_id: str, processed_event: Dict[str, Any]) -> None:
        """Callback and event to the subscribers and update data."""
        self._update_device(device_id, processed_event)

        for subscriber in self._ws_subscriptions:
            subscriber({device_id: self._processed_data[device_id]})

    def _update_device(self, device_id: str, processed_update: Dict[str, Any]) -> None:
        """Update internal state of a device."""
        self._processed_data.setdefault(device_id, {}).update(processed_update)


class ProtectApiClient(BaseApiClient):
    """WIP new API Client class with real Python objects"""

    _minimum_score: int
    _bootstrap: Optional[Bootstrap] = None
    _last_update_dt: Optional[datetime] = None

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        verify_ssl: bool = True,
        session: Optional[aiohttp.ClientSession] = None,
        minimum_score: int = 0,
        debug: bool = False,
    ) -> None:
        super().__init__(
            host=host, port=port, username=username, password=password, verify_ssl=verify_ssl, session=session
        )

        self._minimum_score = minimum_score

        if debug:
            set_debug()

    async def update(self, force: bool = False) -> Union[Bootstrap, List[Event]]:
        """Updates the state of devices."""

        now = time.monotonic()
        now_dt = datetime.now()
        if force and self.ws_connection is not None:
            self.disconnect_ws()
            self._last_update = NEVER_RAN
            self._last_websocket_check = NEVER_RAN

        if self._bootstrap is None or now - self._last_update > DEVICE_UPDATE_INTERVAL:
            self._last_update = now
            data = await self.api_request_obj("bootstrap")
            self._bootstrap = Bootstrap.from_unifi_dict(**data, api=self)

        active_ws = await self.check_ws()
        # If the websocket is connected/connecting
        # we do not need to get events
        if active_ws:
            _LOGGER.debug("Skipping update since websocket is active")
            return self._bootstrap

        events = await self.get_events(start=self._last_update_dt, end=now_dt)
        for event in events:
            self.bootstrap.process_event(event)

        self._last_update = now
        self._last_update_dt = now_dt
        return events

    def _process_ws_message(self, msg: aiohttp.WSMessage) -> None:
        packet = WSPacket(msg.data)
        self.bootstrap.process_ws_packet(packet)

    @property
    def bootstrap(self) -> Bootstrap:
        if self._bootstrap is None:
            raise BadRequest("Client not initalized, run `update` first")

        return self._bootstrap

    async def get_events_raw(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None,
        camera_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get list of events from Protect

        :param start: start time for events
        :param end: end time for events
        :param limit: max number of events to return
        :camera_ids: list of Cameras to get events for

        If limit, start and end are not provided, it will default to all events in the last 24 hours.

        If start is provided, then end or limit must be provided. If end is provided, then start or
        limit must be provided. Otherwise, you will get a 400 error from Unifi Protect

        Providing a list of Camera IDs will not prevent non-camera events from returning.
        """

        # if no parameters are passed in, default to all events from last 24 hours
        if limit is None and start is None and end is None:
            end = datetime.now() + timedelta(seconds=10)
            start = end - timedelta(hours=24)

        params: Dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit

        if start is not None:
            params["start"] = to_js_time(start)

        if end is not None:
            params["end"] = to_js_time(end)

        if camera_ids is not None:
            params["cameras"] = ",".join(camera_ids)

        return await self.api_request_list("events", params=params)

    async def get_events(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None,
        camera_ids: Optional[List[str]] = None,
    ) -> List[Event]:
        """
        Same as `get_events_raw`, except

        * returns actual `Event` objects instead of raw Python dictionaries
        * filers out non-device events
        * filters out events with too low of a score
        """

        response = await self.get_events_raw(start=start, end=end, limit=limit, camera_ids=camera_ids)
        events = []

        for event_dict in response:
            # ignore unknown events
            if event_dict["type"] not in EventType.values():
                _LOGGER.debug("Unknown event type: %s", event_dict["type"])
                continue

            event = create_from_unifi_dict(event_dict, api=self)

            # should never happen
            if not isinstance(event, Event):
                continue

            if event.type.value in EventType.device_events() and event.score >= self._minimum_score:
                events.append(event)

        return events
