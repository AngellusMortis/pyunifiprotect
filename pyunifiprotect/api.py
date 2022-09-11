"""UniFi Protect Server Wrapper."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from http.cookies import Morsel
from ipaddress import IPv4Address
import logging
from pathlib import Path
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Set, Type, Union, cast
from urllib.parse import urljoin
from uuid import UUID

import aiofiles
import aiohttp
from aiohttp import CookieJar, client_exceptions
import orjson

from pyunifiprotect.data import (
    NVR,
    Bootstrap,
    Bridge,
    Camera,
    Doorlock,
    Event,
    EventType,
    Light,
    Liveview,
    ModelType,
    ProtectAdoptableDeviceModel,
    ProtectModel,
    Sensor,
    SmartDetectObjectType,
    SmartDetectTrack,
    Viewer,
    WSPacket,
    WSSubscriptionMessage,
    create_from_unifi_dict,
)
from pyunifiprotect.data.base import ProtectModelWithId
from pyunifiprotect.data.devices import Chime
from pyunifiprotect.data.types import IteratorCallback, ProgressCallback, RecordingMode
from pyunifiprotect.exceptions import BadRequest, NotAuthorized, NvrError
from pyunifiprotect.utils import (
    decode_token_cookie,
    get_response_reason,
    ip_from_host,
    set_debug,
    to_js_time,
    utc_now,
)
from pyunifiprotect.websocket import Websocket

TOKEN_COOKIE_MAX_EXP_SECONDS = 60

NEVER_RAN = -1000
# how many seconds before the bootstrap is refreshed from Protect
DEVICE_UPDATE_INTERVAL = 900
# retry timeout for thumbnails/heatmaps
RETRY_TIMEOUT = 10
EA_WARNING = """
You are running version %s of UniFi Protect, which is an Early Access version. Early Access versions of UniFi Protect are not supported for Home Asssitant.

If have an error, please report errors to https://github.com/AngellusMortis/pyunifiprotect first. DO NOT REPORT EA ISSUES TO HOME ASSISTANT CORE.

It is recommended you downgrade to a stable version. https://www.home-assistant.io/integrations/unifiprotect#downgrading-unifi-protect.
"""
IS_HA = "homeassistant" in sys.modules


_LOGGER = logging.getLogger(__name__)

# TODO:
# Backups
# * GET /backups - list backends
# * POST /backups/import - import backup
# * POST /backups - create backup
# * GET /backups/{id} - download backup
# * POST /backups/{id}/restore - restore backup
# * DELETE /backups/{id} - delete backup
#
# Cameras
# * POST /cameras/{id}/reset - factory reset camera
# * POST /cameras/{id}/reset-isp - reset ISP settings
# * POST /cameras/{id}/reset-isp - reset ISP settings
# * POST /cameras/{id}/wake - battery powered cameras
# * POST /cameras/{id}/sleep
# * GET /cameras/{id}/live-heatmap - add live heatmap to WebRTC stream
# * GET /cameras/{id}/enable-control - PTZ controls
# * GET /cameras/{id}/disable-control
# * POST /cameras/{id}/move
# * POST /cameras/{id}/ptz/position
# * GET|POST /cameras/{id}/ptz/preset
# * GET /cameras/{id}/ptz/snapshot
# * POST /cameras/{id}/ptz/goto
# * GET /cameras/{id}/analytics-heatmap - analytics
# * GET /cameras/{id}/analytics-detections
# * GET /cameras/{id}/wifi-list - WiFi scan
# * POST /cameras/{id}/wifi-setup - Change WiFi settings
# * GET /cameras/{id}/playback-history
# * GET|POST|DELETE /cameras/{id}/sharedStream - stream sharing, unfinished?
#
# Device Groups
# * GET|POST|PUT|DELETE /device-groups
# * GET|PATCH|DELETE /device-groups/{id}
# * PATCH /device-groups/{id}/items
#
# Events
# POST /events/{id}/animated-thumbnail
#
# Lights
# POST /lights/{id}/locate
#
# NVR
# GET|PATCH /nvr/device-password
#
# Schedules
# GET|POST /recordingSchedules
# PATCH|DELETE /recordingSchedules/{id}
#
# Sensors
# POST /sensors/{id}/locate
#
# Timeline
# GET /timeline


class BaseApiClient:
    _host: str
    _port: int
    _username: str
    _password: str
    _verify_ssl: bool

    _is_authenticated: bool = False
    _last_update: float = NEVER_RAN
    _last_ws_status: bool = False
    _last_token_cookie: Morsel[str] | None = None
    _last_token_cookie_decode: Optional[Dict[str, Any]] = None
    _session: Optional[aiohttp.ClientSession] = None

    headers: Optional[Dict[str, str]] = None
    _websocket: Optional[Websocket] = None

    api_path: str = "/proxy/protect/api/"
    ws_path: str = "/proxy/protect/ws/updates"

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        verify_ssl: bool = True,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        self._auth_lock = asyncio.Lock()
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
    def ws_url(self) -> str:
        url = f"wss://{self._host}"
        if self._port != 443:
            url += f":{self._port}"

        url += self.ws_path
        last_update_id = self._get_last_update_id()
        if last_update_id is None:
            return url
        return f"{url}?lastUpdateId={last_update_id}"

    async def get_session(self) -> aiohttp.ClientSession:
        """Gets or creates current client session"""

        if self._session is None or self._session.closed:
            if self._session is not None and self._session.closed:
                _LOGGER.debug("Session was closed, creating a new one")
            # need unsafe to access httponly cookies
            self._session = aiohttp.ClientSession(cookie_jar=CookieJar(unsafe=True))

        return self._session

    async def get_websocket(self) -> Websocket:
        """Gets or creates current Websocket."""

        async def _auth(force: bool) -> Optional[Dict[str, str]]:
            if force:
                if self._session is not None:
                    self._session.cookie_jar.clear()
                self.headers = None

            await self.ensure_authenticated()
            return self.headers

        if self._websocket is None:
            self._websocket = Websocket(self.ws_url, _auth, verify=self._verify_ssl)
            self._websocket.subscribe(self._process_ws_message)

        return self._websocket

    async def close_session(self) -> None:
        """Closing and delets client session"""

        if self._session is not None:
            await self._session.close()
            self._session = None

    async def request(
        self, method: str, url: str, require_auth: bool = False, auto_close: bool = True, **kwargs: Any
    ) -> aiohttp.ClientResponse:
        """Make a request to UniFi Protect"""

        if require_auth:
            await self.ensure_authenticated()

        url = urljoin(self.base_url, url)
        headers = kwargs.get("headers") or self.headers
        _LOGGER.debug("Request url: %s", url)
        if not self._verify_ssl:
            kwargs["ssl"] = False
        session = await self.get_session()

        for attempt in range(2):
            try:
                req_context = session.request(method, url, headers=headers, **kwargs)
                response = await req_context.__aenter__()  # pylint: disable=unnecessary-dunder-call

                self._update_last_token_cookie(response)
                if auto_close:
                    try:
                        _LOGGER.debug("%s %s %s", response.status, response.content_type, response)
                        response.release()
                    except Exception:
                        # make sure response is released
                        response.release()
                        # re-raise exception
                        raise

                return response
            except aiohttp.ServerDisconnectedError as err:
                # If the server disconnected, try again
                # since HTTP/1.1 allows the server to disconnect
                # at any time
                if attempt == 0:
                    continue
                raise NvrError(f"Error requesting data from {self._host}: {err}") from err
            except client_exceptions.ClientError as err:
                raise NvrError(f"Error requesting data from {self._host}: {err}") from err

        # should never happen
        raise NvrError(f"Error requesting data from {self._host}")

    async def api_request_raw(
        self,
        url: str,
        method: str = "get",
        require_auth: bool = True,
        raise_exception: bool = True,
        **kwargs: Any,
    ) -> Optional[bytes]:
        """Make a request to UniFi Protect API"""

        url = urljoin(self.api_path, url)
        response = await self.request(method, url, require_auth=require_auth, auto_close=False, **kwargs)

        try:
            if response.status != 200:
                reason = await get_response_reason(response)
                msg = "Request failed: %s - Status: %s - Reason: %s"
                if raise_exception:
                    if response.status in (401, 403):
                        raise NotAuthorized(msg % (url, response.status, reason))
                    if response.status >= 400 and response.status < 500:
                        raise BadRequest(msg % (url, response.status, reason))
                    raise NvrError(msg % (url, response.status, reason))
                _LOGGER.debug(msg, url, response.status, reason)
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
            json_data: Union[List[Any], Dict[str, Any]] = orjson.loads(data)
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
        if self._auth_lock.locked():
            # If an auth is already in progress
            # do not start another one
            async with self._auth_lock:
                return

        async with self._auth_lock:
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
            self._update_last_token_cookie(response)
            _LOGGER.debug("Authenticated successfully!")

    def _update_last_token_cookie(self, response: aiohttp.ClientResponse) -> None:
        """Update the last token cookie."""
        if (token_cookie := response.cookies.get("TOKEN")) and token_cookie != self._last_token_cookie:
            self._last_token_cookie = token_cookie
            self._last_token_cookie_decode = None

    def is_authenticated(self) -> bool:
        """Check to see if we are already authenticated."""
        if self._session is None:
            return False

        if self._is_authenticated is False:
            return False

        if self._last_token_cookie is None:
            return False

        # Lazy decode the token cookie
        if self._last_token_cookie and self._last_token_cookie_decode is None:
            self._last_token_cookie_decode = decode_token_cookie(self._last_token_cookie)

        if self._last_token_cookie_decode is None or "exp" not in self._last_token_cookie_decode:
            return False

        token_expires_at = self._last_token_cookie_decode["exp"]
        max_expire_time = time.time() + TOKEN_COOKIE_MAX_EXP_SECONDS

        if token_expires_at < max_expire_time:
            return False

        return True

    async def async_connect_ws(self, force: bool) -> None:
        """Connect to Websocket."""

        if force and self._websocket is not None:
            await self._websocket.disconnect()
            self._websocket = None

        websocket = await self.get_websocket()
        # important to make sure WS URL is always current
        websocket.url = self.ws_url

        if not websocket.is_connected:
            self._last_ws_status = False
            await websocket.connect()

    async def async_disconnect_ws(self) -> None:
        """Disconnect from Websocket."""

        if self._websocket is None:
            return
        await self._websocket.disconnect()

    def check_ws(self) -> bool:
        """Checks current state of Websocket."""

        if self._websocket is None:
            return False

        if not self._websocket.is_connected:
            log = _LOGGER.debug
            if self._last_ws_status:
                log = _LOGGER.warning
            log("Websocket connection not active, failing back to polling")
        elif not self._last_ws_status:
            _LOGGER.info("Websocket re-connected successfully")

        self._last_ws_status = self._websocket.is_connected
        return self._last_ws_status

    def _process_ws_message(self, msg: aiohttp.WSMessage) -> None:
        raise NotImplementedError()

    def _get_last_update_id(self) -> Optional[UUID]:
        raise NotImplementedError()


class ProtectApiClient(BaseApiClient):
    """
    Main UFP API Client

    UniFi Protect is a full async application. "normal" use of interacting with it is
    to call `.update()` which will initialize the `.bootstrap` and create a Websocket
    connection to UFP. This Websocket connection will emit messages that will automatically
    update the `.bootstrap` over time. Caling `.udpate` again (without `force`) will
    verify the integry of the Websocket connection.

    You can use the `.get_` methods to one off pull devices from the UFP API, but should
    not be used for building an aplication on top of.

    All objects inside of `.bootstrap` have a refernce back to the API client so they can
    use `.save_device()` and update themselves using their own `.set_` methods on the object.

    Args:
        host: UFP hostname / IP address
        port: UFP HTTPS port
        username: UFP username
        password: UFP password
        verify_ssl: Verify HTTPS certificate (default: `True`)
        session: Optional aiohttp session to use (default: generate one)
        override_connection_host: Use `host` as your `connection_host` for RTSP stream instead of using the one provided by UniFi Protect.
        minimum_score: minimum score for events (default: `0`)
        subscribed_models: Model types you want to filter events for WS. You will need to manually check the bootstrap for updates for events that not subscibred.
        ignore_stats: Ignore storage, system, etc. stats/metrics from NVR and cameras (default: false)
        debug: Use full type validation (default: false)
    """

    _minimum_score: int
    _subscribed_models: Set[ModelType]
    _ignore_stats: bool
    _ws_subscriptions: List[Callable[[WSSubscriptionMessage], None]]
    _bootstrap: Optional[Bootstrap] = None
    _last_update_dt: Optional[datetime] = None
    _connection_host: Optional[Union[IPv4Address, str]] = None

    ignore_unadopted: bool

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        verify_ssl: bool = True,
        session: Optional[aiohttp.ClientSession] = None,
        override_connection_host: bool = False,
        minimum_score: int = 0,
        subscribed_models: Optional[Set[ModelType]] = None,
        ignore_stats: bool = False,
        ignore_unadopted: bool = True,
        debug: bool = False,
    ) -> None:
        super().__init__(
            host=host,
            port=port,
            username=username,
            password=password,
            verify_ssl=verify_ssl,
            session=session,
        )

        self._minimum_score = minimum_score
        self._subscribed_models = subscribed_models or set()
        self._ignore_stats = ignore_stats
        self._ws_subscriptions = []
        self.ignore_unadopted = ignore_unadopted

        if override_connection_host:
            self._connection_host = ip_from_host(self._host)

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
    def connection_host(self) -> Union[IPv4Address, str]:
        """Connection host to use for generating RTSP URLs"""

        if self._connection_host is None:
            # fallback if cannot find user supplied host
            index = 0
            try:
                # check if user supplied host is avaiable
                index = self.bootstrap.nvr.hosts.index(self._host)
            except ValueError:
                # check if IP of user supplied host is avaiable
                host = ip_from_host(self._host)
                try:
                    index = self.bootstrap.nvr.hosts.index(host)
                except ValueError:
                    pass

            self._connection_host = self.bootstrap.nvr.hosts[index]

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
            self._last_update = NEVER_RAN
            self._last_update_dt = max_event_dt

        bootstrap_updated = False
        if self._bootstrap is None or now - self._last_update > DEVICE_UPDATE_INTERVAL:
            bootstrap_updated = True
            self._bootstrap = await self.get_bootstrap()
            if self._last_update == NEVER_RAN and IS_HA and self._bootstrap.nvr.version.is_prerelease:
                _LOGGER.warning(EA_WARNING, self._bootstrap.nvr.version)

            self._last_update = now
            self._last_update_dt = now_dt

        await self.async_connect_ws(force)
        active_ws = self.check_ws()
        if not bootstrap_updated and active_ws:
            # If the websocket is connected/connecting
            # we do not need to get events
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

    def _get_last_update_id(self) -> Optional[UUID]:
        if self._bootstrap is None:
            return None
        return self._bootstrap.last_update_id

    def _process_ws_message(self, msg: aiohttp.WSMessage) -> None:
        packet = WSPacket(msg.data)
        processed_message = self.bootstrap.process_ws_packet(
            packet, models=self._subscribed_models, ignore_stats=self._ignore_stats
        )
        # update websocket URL after every message to ensure the latest last_update_id
        if self._websocket is not None:
            self._websocket.url = self.ws_url

        if processed_message is None:
            return

        self.emit_message(processed_message)

    async def get_events_raw(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None,
        types: Optional[List[EventType]] = None,
        smart_detect_types: Optional[List[SmartDetectObjectType]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get list of events from Protect

        Args:
            start: start time for events
            end: end time for events
            limit: max number of events to return
            types: list of EventTypes to get events for

        If `limit`, `start` and `end` are not provided, it will default to all events in the last 24 hours.

        If `start` is provided, then `end` or `limit` must be provided. If `end` is provided, then `start` or
        `limit` must be provided. Otherwise, you will get a 400 error from UniFi Protect
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

        if types is not None:
            params["types"] = [e.value for e in types]

        if smart_detect_types is not None:
            params["smartDetectTypes"] = [e.value for e in smart_detect_types]

        return await self.api_request_list("events", params=params)

    async def get_events(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None,
        types: Optional[List[EventType]] = None,
        smart_detect_types: Optional[List[SmartDetectObjectType]] = None,
    ) -> List[Event]:
        """
        Same as `get_events_raw`, except

        * returns actual `Event` objects instead of raw Python dictionaries
        * filers out non-device events
        * filters out events with too low of a score

        Args:
            start: start time for events
            end: end time for events
            limit: max number of events to return
            types: list of EventTypes to get events for
            smart_detect_types: Filters the Smart detection types for the events

        If `limit`, `start` and `end` are not provided, it will default to all events in the last 24 hours.

        If `start` is provided, then `end` or `limit` must be provided. If `end` is provided, then `start` or
        `limit` must be provided. Otherwise, you will get a 400 error from UniFi Protect
        """

        response = await self.get_events_raw(
            start=start, end=end, limit=limit, types=types, smart_detect_types=smart_detect_types
        )
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
        # fix for UniFi Protect bug, some cameras may come back with and old recording mode
        # "motion" and "smartDetect" recording modes was combined into "detections" in Protect 1.20.0
        call_again = False
        for camera_dict in data["cameras"]:
            if camera_dict.get("recordingSettings", {}).get("mode", "detections") in ("motion", "smartDetect"):
                await self.update_device(
                    ModelType.CAMERA, camera_dict["id"], {"recordingSettings": {"mode": RecordingMode.DETECTIONS.value}}
                )
                call_again = True

        if call_again:
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
            if self.ignore_unadopted and isinstance(obj, ProtectAdoptableDeviceModel) and not obj.is_adopted:
                continue

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

    async def get_doorlocks(self) -> List[Doorlock]:
        """
        Gets the list of doorlocks straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.doorlocks`
        """
        return cast(List[Doorlock], await self.get_devices(ModelType.DOORLOCK, Doorlock))

    async def get_chimes(self) -> List[Chime]:
        """
        Gets the list of chimes straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.chimes`
        """
        return cast(List[Chime], await self.get_devices(ModelType.CHIME, Chime))

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
        self, model_type: ModelType, device_id: str, expected_type: Optional[Type[ProtectModelWithId]] = None
    ) -> ProtectModelWithId:
        """Gets a device give the device model_type and id, converted into Python object"""
        obj = create_from_unifi_dict(await self.get_device_raw(model_type, device_id), api=self)

        if expected_type is not None and not isinstance(obj, expected_type):
            raise NvrError(f"Unexpected model returned: {obj.model}")
        if self.ignore_unadopted and isinstance(obj, ProtectAdoptableDeviceModel) and not obj.is_adopted:
            raise NvrError("Device is not adopted")

        return cast(ProtectModelWithId, obj)

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

    async def get_doorlock(self, device_id: str) -> Doorlock:
        """
        Gets a doorlock straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.doorlocks[device_id]`
        """
        return cast(Doorlock, await self.get_device(ModelType.DOORLOCK, device_id, Doorlock))

    async def get_chime(self, device_id: str) -> Chime:
        """
        Gets a chime straight from the NVR.

        The websocket is connected and running, you likely just want to use `self.bootstrap.chimes[device_id]`
        """
        return cast(Chime, await self.get_device(ModelType.CHIME, device_id, Chime))

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
        dt: Optional[datetime] = None,
    ) -> Optional[bytes]:
        """
        Gets snapshot for a camera.

        Datetime of screenshot is approximate. It may be +/- a few seconds.
        """

        params = {
            "ts": to_js_time(dt or utc_now()),
            "force": "true",
        }

        if width is not None:
            params.update({"w": width})

        if height is not None:
            params.update({"h": height})

        path = "snapshot"
        if dt is not None:
            path = "recording-snapshot"
            del params["force"]

        return await self.api_request_raw(f"cameras/{camera_id}/{path}", params=params, raise_exception=False)

    async def get_package_camera_snapshot(
        self,
        camera_id: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
        dt: Optional[datetime] = None,
    ) -> Optional[bytes]:
        """
        Gets snapshot from the package camera.

        Datetime of screenshot is approximate. It may be +/- a few seconds.
        """

        params = {
            "ts": to_js_time(dt or utc_now()),
            "force": "true",
        }

        if width is not None:
            params.update({"w": width})

        if height is not None:
            params.update({"h": height})

        path = "package-snapshot"
        if dt is not None:
            path = "recording-snapshot"
            del params["force"]
            params.update({"lens": 2})

        return await self.api_request_raw(f"cameras/{camera_id}/{path}", params=params, raise_exception=False)

    async def _stream_response(
        self,
        response: aiohttp.ClientResponse,
        chunk_size: int,
        iterator_callback: Optional[IteratorCallback] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> None:
        total = response.content_length or 0
        current = 0
        if iterator_callback is not None:
            await iterator_callback(total, None)
        async for chunk in response.content.iter_chunked(chunk_size):
            step = len(chunk)
            current += step
            if iterator_callback is not None:
                await iterator_callback(total, chunk)
            if progress_callback is not None:
                await progress_callback(step, current, total)

    async def get_camera_video(
        self,
        camera_id: str,
        start: datetime,
        end: datetime,
        channel_index: int = 0,
        validate_channel_id: bool = True,
        output_file: Optional[Path] = None,
        iterator_callback: Optional[IteratorCallback] = None,
        progress_callback: Optional[ProgressCallback] = None,
        chunk_size: int = 65536,
        fps: Optional[int] = None,
    ) -> Optional[bytes]:
        """
        Exports MP4 video from a given camera at a specific time.

        Start/End of video export are approximate. It may be +/- a few seconds.

        It is recommended to provide a output file or progress callback for larger
        video clips, otherwise the full video must be downloaded to memory before
        being written.

        Providing the `fps` parameter creates a "timelapse" export wtih the given FPS
        value. Protect app gives the options for 60x (fps=4), 120x (fps=8), 300x
        (fps=20), and 600x (fps=40).
        """

        if validate_channel_id and self._bootstrap is not None:
            camera = self._bootstrap.cameras[camera_id]
            try:
                camera.channels[channel_index]
            except IndexError as e:
                raise BadRequest from e

        params = {
            "camera": camera_id,
            "start": to_js_time(start),
            "end": to_js_time(end),
        }

        if fps is not None:
            params["fps"] = fps
            params["type"] = "timelapse"

        if channel_index == 3:
            params.update({"lens": 2})
        else:
            params.update({"channel": channel_index})

        path = "video/export"
        if iterator_callback is None and progress_callback is None and output_file is None:
            return await self.api_request_raw(path, params=params, raise_exception=False)

        r = await self.request("get", urljoin(self.api_path, path), auto_close=False, params=params)
        if output_file is not None:
            async with aiofiles.open(output_file, "wb") as output:

                async def callback(total: int, chunk: bytes | None) -> None:
                    if iterator_callback is not None:
                        await iterator_callback(total, chunk)
                    if chunk is not None:
                        await output.write(chunk)

                await self._stream_response(r, chunk_size, callback, progress_callback)
        else:
            await self._stream_response(r, chunk_size, iterator_callback, progress_callback)
        r.close()
        return None

    async def _get_image_with_retry(
        self, path: str, retry_timeout: int = RETRY_TIMEOUT, **kwargs: Any
    ) -> Optional[bytes]:
        """
        Retries image request until it returns or timesout. Used for event images like thumbnails and heatmaps.

        Note: thumbnails / heatmaps do not generate _until after the event ends_. Events that last longer then
        your retry timeout will always return None.
        """

        now = time.monotonic()
        timeout = now + retry_timeout
        data: Optional[bytes] = None
        while data is None and now < timeout:
            data = await self.api_request_raw(path, raise_exception=False, **kwargs)
            if data is None:
                await asyncio.sleep(0.5)
                now = time.monotonic()

        return data

    async def get_event_thumbnail(
        self,
        thumbnail_id: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
        retry_timeout: int = RETRY_TIMEOUT,
    ) -> Optional[bytes]:
        """
        Gets given thumbanail from a given event.

        Thumbnail response is a JPEG image.

        Note: thumbnails / heatmaps do not generate _until after the event ends_. Events that last longer then
        your retry timeout will always return 404.
        """

        params: Dict[str, Any] = {}

        if width is not None:
            params.update({"w": width})

        if height is not None:
            params.update({"h": height})

        # old thumbnail URL use thumbnail ID, which is just `e-{event_id}`
        thumbnail_id = thumbnail_id.replace("e-", "")
        return await self._get_image_with_retry(
            f"events/{thumbnail_id}/thumbnail", params=params, retry_timeout=retry_timeout
        )

    async def get_event_animated_thumbnail(
        self,
        thumbnail_id: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
        *,
        speedup: int = 10,
        retry_timeout: int = RETRY_TIMEOUT,
    ) -> Optional[bytes]:
        """
        Gets given animated thumbanil from a given event.

        Animated thumbnail response is a GIF image.

        Note: thumbnails / do not generate _until after the event ends_. Events that last longer then
        your retry timeout will always return 404.
        """

        params: Dict[str, Any] = {
            "keyFrameOnly": "true",
            "speedup": speedup,
        }

        if width is not None:
            params.update({"w": width})

        if height is not None:
            params.update({"h": height})

        # old thumbnail URL use thumbnail ID, which is just `e-{event_id}`
        thumbnail_id = thumbnail_id.replace("e-", "")
        return await self._get_image_with_retry(
            f"events/{thumbnail_id}/animated-thumbnail", params=params, retry_timeout=retry_timeout
        )

    async def get_event_heatmap(
        self,
        heatmap_id: str,
        retry_timeout: int = RETRY_TIMEOUT,
    ) -> Optional[bytes]:
        """
        Gets given heatmap from a given event.

        Heatmap response is a PNG image.

        Note: thumbnails / heatmaps do not generate _until after the event ends_. Events that last longer then
        your retry timeout will always return None.
        """

        # old heatmap URL use heatmap ID, which is just `e-{event_id}`
        heatmap_id = heatmap_id.replace("e-", "")
        return await self._get_image_with_retry(f"events/{heatmap_id}/heatmap", retry_timeout=retry_timeout)

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

    async def reboot_nvr(self) -> None:
        """Reboots NVR"""

        await self.api_request("nvr/reboot", method="post")

    async def reboot_device(self, model_type: ModelType, device_id: str) -> None:
        """Reboots an adopted device"""

        await self.api_request(f"{model_type.value}s/{device_id}/reboot", method="post")

    async def unadopt_device(self, model_type: ModelType, device_id: str) -> None:
        """Unadopt/Unmanage adopted device"""

        await self.api_request(f"{model_type.value}s/{device_id}", method="delete")

    async def adopt_device(self, model_type: ModelType, device_id: str) -> None:
        """Adopts a device"""

        key = f"{model_type.value}s"
        data = await self.api_request_obj("devices/adopt", method="post", json={key: {device_id: {}}})

        if not data.get(key, {}).get(device_id, {}).get("adopted", False):
            raise BadRequest("Could not adopt device")

    async def close_lock(self, device_id: str) -> None:
        """Close doorlock (lock)"""

        await self.api_request(f"doorlocks/{device_id}/close", method="post")

    async def open_lock(self, device_id: str) -> None:
        """Open doorlock (unlock)"""

        await self.api_request(f"doorlocks/{device_id}/open", method="post")

    async def calibrate_lock(self, device_id: str) -> None:
        """
        Calibrate the doorlock.

        Door must be open and lock unlocked.
        """

        await self.api_request(f"doorlocks/{device_id}/calibrate", method="post", json={"auto": True})

    async def play_speaker(self, device_id: str) -> None:
        """Plays chime tones on a chime"""

        await self.api_request(f"chimes/{device_id}/play-speaker", method="post")

    async def play_buzzer(self, device_id: str) -> None:
        """Plays chime tones on a chime"""

        await self.api_request(f"chimes/{device_id}/play-buzzer", method="post")

    async def clear_tamper_sensor(self, device_id: str) -> None:
        """Clears tamper status for sensor"""

        await self.api_request(f"sensors/{device_id}/clear-tamper-flag", method="post")
