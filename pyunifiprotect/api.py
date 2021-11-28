"""Unifi Protect Server Wrapper."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from ipaddress import IPv4Address
import json as pjson
import logging
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Type, Union, cast
from urllib.parse import urljoin
from uuid import UUID

import aiohttp
from aiohttp import CookieJar, client_exceptions
import jwt
from yarl import URL

from pyunifiprotect.data import (
    NVR,
    Bootstrap,
    Bridge,
    Camera,
    Event,
    EventType,
    Light,
    Liveview,
    ModelType,
    ProtectModel,
    Sensor,
    SmartDetectTrack,
    Viewer,
    WSPacket,
    WSSubscriptionMessage,
    create_from_unifi_dict,
)
from pyunifiprotect.exceptions import BadRequest, NotAuthorized, NvrError
from pyunifiprotect.utils import (
    get_response_reason,
    ip_from_host,
    set_debug,
    to_js_time,
    utc_now,
)

NEVER_RAN = -1000
# how many seconds before the bootstrap is refreshed from Protect
DEVICE_UPDATE_INTERVAL = 60
# how many seconds before before we check for an active WS connection
WEBSOCKET_CHECK_INTERVAL = 120


_LOGGER = logging.getLogger(__name__)


# TODO: Remove when 3.8 support is dropped
if TYPE_CHECKING:
    TaskClass = asyncio.Task[None]
else:
    TaskClass = asyncio.Task


class BaseApiClient:
    _host: str
    _port: int
    _username: str
    _password: str
    _verify_ssl: bool
    _is_authenticated: bool = False
    _last_update: float = NEVER_RAN
    _last_websocket_check: float = NEVER_RAN
    _session: Optional[aiohttp.ClientSession] = None
    _ws_session: Optional[aiohttp.ClientSession] = None
    _ws_connection: Optional[aiohttp.ClientWebSocketResponse] = None
    _ws_task: Optional[TaskClass] = None
    _ws_raw_subscriptions: List[Callable[[aiohttp.WSMessage], None]] = []

    headers: Optional[Dict[str, str]] = None
    last_update_id: Optional[UUID] = None

    api_path: str = "/proxy/protect/api/"
    ws_path: str = "/proxy/protect/ws/"

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

        self._username = username
        self._password = password
        self._verify_ssl = verify_ssl

        if session is not None:
            self._session = session

    @property
    def base_url(self) -> str:
        if self._port != 443:
            return f"https://{self._host}:{self._port}"
        return f"https://{self._host}"

    @property
    def base_ws_url(self) -> str:
        if self._port != 443:
            return f"wss://{self._host}:{self._port}"
        return f"wss://{self._host}"

    @property
    def is_ws_connected(self) -> bool:
        return self._ws_connection is not None

    async def get_session(self) -> aiohttp.ClientSession:
        """Gets or creates current client session"""

        if self._session is None or self._session.closed:
            if self._session is not None and self._session.closed:
                _LOGGER.debug("Session was closed, creating a new one")
            # need unsafe to access httponly cookies
            self._session = aiohttp.ClientSession(cookie_jar=CookieJar(unsafe=True))

        return self._session

    async def close_session(self) -> None:
        """Closing and delets client session"""

        if self._session is not None:
            await self._session.close()
            self._session = None

    async def request(
        self, method: str, url: str, require_auth: bool = False, auto_close: bool = True, **kwargs: Any
    ) -> aiohttp.ClientResponse:
        """Make a request to Unifi Protect"""

        if require_auth:
            await self.ensure_authenticated()

        url = urljoin(self.base_url, url)
        headers = kwargs.get("headers") or self.headers

        _LOGGER.debug("Request url: %s", url)

        session = await self.get_session()
        try:
            if not self._verify_ssl:
                kwargs["ssl"] = False
            req_context = session.request(method, url, headers=headers, **kwargs)
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

        if self._session is not None:
            self._session.cookie_jar.clear()

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

        if self._session is None:
            return False

        if self._is_authenticated is True:
            # Check if token is expired.
            cookies = self._session.cookie_jar.filter_cookies(URL(self.base_url))
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

    def reset_ws(self) -> None:
        """Forcibly resets Websocket"""

        if not self.is_ws_connected:
            return

        if self._ws_task is not None:
            try:
                self._ws_task.cancel()
                self._ws_connection = None
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Could not cancel ws_task")

    async def async_connect_ws(self) -> None:
        """Connect the websocket."""

        if self.is_ws_connected:
            return

        self.reset_ws()
        self._ws_task = asyncio.ensure_future(self._setup_websocket())

    async def async_disconnect_ws(self) -> None:
        """Disconnect the websocket."""

        if self._ws_connection is None:
            return

        await self._ws_connection.close()
        if self._ws_session is not None:
            await self._ws_session.close()
            self._ws_session = None

    async def _message_loop(self, msg: aiohttp.WSMessage) -> bool:
        for sub in self._ws_raw_subscriptions:
            sub(msg)

        if msg.type == aiohttp.WSMsgType.BINARY:
            try:
                self._process_ws_message(msg)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Error processing websocket message")
        elif msg.type == aiohttp.WSMsgType.ERROR:
            _LOGGER.exception("Error from Websocket: %s", msg.data)
            return False

        return True

    async def _setup_websocket(self) -> None:
        await self.ensure_authenticated()

        url = urljoin(f"{self.base_ws_url}{self.ws_path}", "updates")
        if self.last_update_id:
            url += f"?lastUpdateId={self.last_update_id}"

        if not self._ws_session:
            self._ws_session = aiohttp.ClientSession()
        _LOGGER.debug("WS connecting to: %s", url)

        self._ws_connection = await self._ws_session.ws_connect(url, ssl=self._verify_ssl, headers=self.headers)
        try:
            async for msg in self._ws_connection:
                if not await self._message_loop(msg):
                    break
        finally:
            _LOGGER.debug("websocket disconnected")
            self._ws_connection = None

    def subscribe_raw_websocket(self, ws_callback: Callable[[aiohttp.WSMessage], None]) -> Callable[[], None]:
        """
        Subscribe to raw websocket messages.

        Returns a callback that will unsubscribe.
        """

        def _unsub_ws_callback() -> None:
            self._ws_raw_subscriptions.remove(ws_callback)

        _LOGGER.debug("Adding subscription: %s", ws_callback)
        self._ws_raw_subscriptions.append(ws_callback)
        return _unsub_ws_callback

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
        if not self._ws_connection and not first_check:
            log = _LOGGER.debug
            # but only warn if a reconnect attempt was made
            if connect_ws:
                log = _LOGGER.warning
            log("Unifi OS: Websocket connection not active, failing back to polling")

        if self._ws_connection or self._last_websocket_check == now:
            return True
        return False

    def _process_ws_message(self, msg: aiohttp.WSMessage) -> None:
        raise NotImplementedError()


class ProtectApiClient(BaseApiClient):
    """
    Main UFP API Client

    Unifi Protect is a full async application. "normal" use of interacting with it is
    to call `.update()` which will initialize the `.bootstrap` and create a Websocket
    connection to UFP. This Websocket connection will emit messages that will automatically
    update the `.bootstrap` over time. Caling `.udpate` again (without `force`) will
    verify the integry of the Websocket connection.

    You can use the `.get_` methods to one off pull devices from the UFP API, but should
    not be used for building an aplication on top of.

    All objects inside of `.bootstrap` have a refernce back to the API client so they can
    use `.save_device()` and update themselves using their own `.set_` methods on the object.

    """

    _minimum_score: int
    _bootstrap: Optional[Bootstrap] = None
    _last_update_dt: Optional[datetime] = None
    _ws_subscriptions: List[Callable[[WSSubscriptionMessage], None]] = []
    _connection_host: Optional[IPv4Address] = None

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

    @property
    def is_ready(self) -> bool:
        return self._bootstrap is not None

    @property
    def bootstrap(self) -> Bootstrap:
        if self._bootstrap is None:
            raise BadRequest("Client not initalized, run `update` first")

        return self._bootstrap

    @property
    def connection_host(self) -> IPv4Address:
        """Connection host to use for generating RTSP URLs"""

        if self._connection_host is None:
            host = ip_from_host(self._host)

            for connection_host in self.bootstrap.nvr.hosts:
                if connection_host == host:
                    self._connection_host = connection_host
                    break

            if self._connection_host is None:
                self._connection_host = self.bootstrap.nvr.hosts[0]

        return self._connection_host

    async def update(self, force: bool = False) -> Optional[Bootstrap]:
        """
        Updates the state of devices, initalizes `.bootstrap` and
        connects to UFP Websocket for real time updates

        You can use the various other `get_` methods if you need one off data from UFP
        """

        now = time.monotonic()
        now_dt = utc_now()
        max_event_dt = now_dt - timedelta(hours=24)
        if force:
            self.reset_ws()
            self._last_update = NEVER_RAN
            self._last_update_dt = max_event_dt
            self._last_websocket_check = NEVER_RAN

        if self._bootstrap is None or now - self._last_update > DEVICE_UPDATE_INTERVAL:
            self._last_update = now
            self._last_update_dt = now_dt
            self._bootstrap = await self.get_bootstrap()

        active_ws = await self.check_ws()
        # If the websocket is connected/connecting
        # we do not need to get events
        if active_ws:
            _LOGGER.debug("Skipping update since websocket is active")
            return None

        events = await self.get_events(start=self._last_update_dt or max_event_dt, end=now_dt)
        for event in events:
            self.bootstrap.process_event(event)

        self._last_update = now
        self._last_update_dt = now_dt
        return self._bootstrap

    def emit_message(self, msg: WSSubscriptionMessage) -> None:
        for sub in self._ws_subscriptions:
            try:
                sub(msg)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Exception while running subscription handler")

    def _process_ws_message(self, msg: aiohttp.WSMessage) -> None:
        packet = WSPacket(msg.data)
        processed_message = self.bootstrap.process_ws_packet(packet)

        if processed_message is None:
            return

        self.emit_message(processed_message)

    async def get_events_raw(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None,
        camera_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get list of events from Protect

        Args:

        * `start`: start time for events
        * `end`: end time for events
        * `limit`: max number of events to return
        * `camera_ids`: list of Cameras to get events for

        If `limit`, `start` and `end` are not provided, it will default to all events in the last 24 hours.

        If `start` is provided, then `end` or `limit` must be provided. If `end` is provided, then `start` or
        `limit` must be provided. Otherwise, you will get a 400 error from Unifi Protect

        Providing a list of Camera IDs will not prevent non-camera events from returning.
        """

        # if no parameters are passed in, default to all events from last 24 hours
        if limit is None and start is None and end is None:
            end = utc_now() + timedelta(seconds=10)
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
            if "type" not in event_dict or event_dict["type"] not in EventType.values():
                _LOGGER.debug("Unknown event type: %s", event_dict)
                continue

            event = create_from_unifi_dict(event_dict, api=self)

            # should never happen
            if not isinstance(event, Event):
                continue

            if event.type.value in EventType.device_events() and event.score >= self._minimum_score:
                events.append(event)

        return events

    def subscribe_websocket(self, ws_callback: Callable[[WSSubscriptionMessage], None]) -> Callable[[], None]:
        """
        Subscribe to websocket events.

        Returns a callback that will unsubscribe.
        """

        def _unsub_ws_callback() -> None:
            self._ws_subscriptions.remove(ws_callback)

        _LOGGER.debug("Adding subscription: %s", ws_callback)
        self._ws_subscriptions.append(ws_callback)
        return _unsub_ws_callback

    async def get_bootstrap(self) -> Bootstrap:
        """
        Gets bootstrap object from UFP instance

        This is a great alternative if you need metadata about the NVR without connecting to the Websocket
        """

        data = await self.api_request_obj("bootstrap")
        return Bootstrap.from_unifi_dict(**data, api=self)

    async def get_devices_raw(self, model_type: ModelType) -> List[Dict[str, Any]]:
        """Gets a raw device list given a model_type"""
        return await self.api_request_list(f"{model_type.value}s")

    async def get_devices(
        self, model_type: ModelType, expected_type: Optional[Type[ProtectModel]] = None
    ) -> List[ProtectModel]:
        """Gets a device list given a model_type, converted into Python objects"""
        objs: List[ProtectModel] = []

        for obj_dict in await self.get_devices_raw(model_type):
            obj = create_from_unifi_dict(obj_dict)

            if expected_type is not None and not isinstance(obj, expected_type):
                raise NvrError(f"Unexpected model returned: {obj.model}")

            objs.append(obj)

        return objs

    async def get_cameras(self) -> List[Camera]:
        """
        Gets the list of cameras straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.cameras`
        """
        return cast(List[Camera], await self.get_devices(ModelType.CAMERA, Camera))

    async def get_lights(self) -> List[Light]:
        """
        Gets the list of lights straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.lights`
        """
        return cast(List[Light], await self.get_devices(ModelType.LIGHT, Light))

    async def get_sensors(self) -> List[Sensor]:
        """
        Gets the list of sensors straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.sensors`
        """
        return cast(List[Sensor], await self.get_devices(ModelType.SENSOR, Sensor))

    async def get_viewers(self) -> List[Viewer]:
        """
        Gets the list of viewers straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.viewers`
        """
        return cast(List[Viewer], await self.get_devices(ModelType.VIEWPORT, Viewer))

    async def get_bridges(self) -> List[Bridge]:
        """
        Gets the list of bridges straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.bridges`
        """
        return cast(List[Bridge], await self.get_devices(ModelType.BRIDGE, Bridge))

    async def get_liveviews(self) -> List[Liveview]:
        """
        Gets the list of liveviews straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.liveviews`
        """
        return cast(List[Liveview], await self.get_devices(ModelType.LIVEVIEW, Liveview))

    async def get_device_raw(self, model_type: ModelType, device_id: str) -> Dict[str, Any]:
        """Gets a raw device give the device model_type and id"""
        return await self.api_request_obj(f"{model_type.value}s/{device_id}")

    async def get_device(
        self, model_type: ModelType, device_id: str, expected_type: Optional[Type[ProtectModel]] = None
    ) -> ProtectModel:
        """Gets a device give the device model_type and id, converted into Python object"""
        obj = create_from_unifi_dict(await self.get_device_raw(model_type, device_id), api=self)

        if expected_type is not None and not isinstance(obj, expected_type):
            raise NvrError(f"Unexpected model returned: {obj.model}")

        return obj

    async def get_nvr(self) -> NVR:
        """
        Gets an NVR object straight from the NVR.

        This is a great alternative if you need metadata about the NVR without connecting to the Websocket
        """

        data = await self.api_request_obj("nvr")
        return NVR.from_unifi_dict(**data, api=self)

    async def get_event(self, event_id: str) -> Event:
        """
        Gets an event straight from the NVR.

        This is a great alternative if the event is no longer in the `self.bootstrap.events[event_id]` cache
        """
        return cast(Event, await self.get_device(ModelType.EVENT, event_id, Event))

    async def get_camera(self, device_id: str) -> Camera:
        """
        Gets a camera straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.cameras[device_id]`
        """
        return cast(Camera, await self.get_device(ModelType.CAMERA, device_id, Camera))

    async def get_light(self, device_id: str) -> Light:
        """
        Gets a light straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.lights[device_id]`
        """
        return cast(Light, await self.get_device(ModelType.LIGHT, device_id, Light))

    async def get_sensor(self, device_id: str) -> Sensor:
        """
        Gets a sensor straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.sensors[device_id]`
        """
        return cast(Sensor, await self.get_device(ModelType.SENSOR, device_id, Sensor))

    async def get_viewer(self, device_id: str) -> Viewer:
        """
        Gets a viewer straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.viewers[device_id]`
        """
        return cast(Viewer, await self.get_device(ModelType.VIEWPORT, device_id, Viewer))

    async def get_bridge(self, device_id: str) -> Bridge:
        """
        Gets a bridge straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.bridges[device_id]`
        """
        return cast(Bridge, await self.get_device(ModelType.BRIDGE, device_id, Bridge))

    async def get_liveview(self, device_id: str) -> Liveview:
        """
        Gets a liveview straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.liveviews[device_id]`
        """
        return cast(Liveview, await self.get_device(ModelType.LIVEVIEW, device_id, Liveview))

    async def get_camera_snapshot(
        self,
        camera_id: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> Optional[bytes]:
        """Gets a snapshot from a camera"""

        dt = utc_now()  # ts is only used as a cache buster
        params = {
            "ts": to_js_time(dt),
            "force": "true",
        }

        if width is not None:
            params.update({"w": width})

        if height is not None:
            params.update({"h": height})

        return await self.api_request_raw(f"cameras/{camera_id}/snapshot", params=params, raise_exception=False)

    async def get_camera_video(
        self, camera_id: str, start: datetime, end: datetime, channel_index: int = 0, validate_channel_id: bool = True
    ) -> Optional[bytes]:
        """Exports MP4 video from a given camera at a specific time"""

        if validate_channel_id and self._bootstrap is not None:
            camera = self._bootstrap.cameras[camera_id]
            try:
                camera.channels[channel_index]
            except IndexError as e:
                raise BadRequest from e

        params = {
            "camera": camera_id,
            "channel": channel_index,
            "start": to_js_time(start),
            "end": to_js_time(end),
        }

        return await self.api_request_raw("video/export", params=params, raise_exception=False)

    async def get_event_thumbnail(
        self, thumbnail_id: str, width: Optional[int] = None, height: Optional[int] = None
    ) -> Optional[bytes]:
        """Gets given thumbanil from a given event"""

        params: Dict[str, Any] = {}

        if width is not None:
            params.update({"w": width})

        if height is not None:
            params.update({"h": height})

        return await self.api_request_raw(f"thumbnails/{thumbnail_id}", params=params, raise_exception=False)

    async def get_event_heatmap(self, heatmap_id: str) -> Optional[bytes]:
        """Gets given heatmap from a given event"""

        return await self.api_request_raw(f"heatmaps/{heatmap_id}", raise_exception=False)

    async def get_event_smart_detect_track_raw(self, event_id: str) -> Dict[str, Any]:
        """Gets raw Smart Detect Track for a Smart Detection"""

        return await self.api_request_obj(f"events/{event_id}/smartDetectTrack")

    async def get_event_smart_detect_track(self, event_id: str) -> SmartDetectTrack:
        """Gets raw Smart Detect Track for a Smart Detection"""

        data = await self.api_request_obj(f"events/{event_id}/smartDetectTrack")

        return SmartDetectTrack.from_unifi_dict(api=self, **data)

    async def update_device(self, model_type: ModelType, device_id: str, data: Dict[str, Any]) -> None:
        """
        Sends an update for a device back to UFP

        USE WITH CAUTION, all possible combinations of updating objects have not been fully tested.
        May have unexpected side effects.

        Tested updates have been added a methods on applicable devices.
        """

        await self.api_request(f"{model_type.value}s/{device_id}", method="patch", json=data)

    async def update_nvr(self, data: Dict[str, Any]) -> None:
        """
        Sends an update for main UFP NVR device

        USE WITH CAUTION, all possible combinations of updating objects have not been fully tested.
        May have unexpected side effects.

        Tested updates have been added a methods on applicable devices.
        """

        await self.api_request("nvr", method="patch", json=data)

    async def reboot_device(self, model_type: ModelType, device_id: str) -> None:
        """Reboots an adopted device"""

        await self.api_request(f"{model_type.value}s/{device_id}/reboot", method="post")
