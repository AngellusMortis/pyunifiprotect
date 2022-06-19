import asyncio
from collections.abc import Callable
import logging
import time
from typing import Any, Coroutine, Dict, List, Optional

from aiohttp import (
    ClientError,
    ClientSession,
    ClientWebSocketResponse,
    WSMessage,
    WSMsgType,
)

_LOGGER = logging.getLogger(__name__)
CALLBACK_TYPE = Callable[..., Coroutine[Any, Any, Optional[Dict[str, str]]]]
RECENT_FAILURE_CUT_OFF = 30


class Websocket:
    url: str
    verify: bool
    timeout_interval: int
    backoff: int
    _auth: CALLBACK_TYPE
    _timeout: float
    _ws_subscriptions: List[Callable[[WSMessage], None]]
    _connect_lock: asyncio.Lock

    _headers: Optional[Dict[str, str]] = None
    _timer_task: Optional[asyncio.Task[None]] = None
    _ws_connection: Optional[ClientWebSocketResponse] = None
    _last_connect: float = -1000
    _recent_failures: int = 0

    def __init__(
        self,
        url: str,
        auth_callback: CALLBACK_TYPE,
        timeout: int = 30,
        backoff: int = 10,
        verify: bool = True,
    ) -> None:
        self.url = url
        self.timeout_interval = timeout
        self.backoff = backoff
        self.verify = verify
        self._auth = auth_callback  # type: ignore
        self._timeout = time.monotonic()
        self._ws_subscriptions = []
        self._connect_lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        """Is Websocket connected"""
        return self._ws_connection is not None

    def _get_session(self) -> ClientSession:
        # for testing, to make easier to mock
        return ClientSession()

    def _process_message(self, msg: WSMessage) -> bool:
        if msg.type == WSMsgType.ERROR:
            _LOGGER.exception("Error from Websocket: %s", msg.data)
            return False

        for sub in self._ws_subscriptions:
            try:
                sub(msg)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Error processing websocket message")

        return True

    async def _websocket_loop(self, start_event: asyncio.Event) -> None:
        _LOGGER.debug("Connecting WS to %s", self.url)
        self._headers = await self._auth(self._should_reset_auth)

        session = self._get_session()
        # catch any and all errors for Websocket so we can clean up correctly
        try:
            self._ws_connection = await session.ws_connect(self.url, ssl=self.verify, headers=self._headers)
            start_event.set()

            await self._reset_timeout()
            async for msg in self._ws_connection:
                if not self._process_message(msg):
                    break
                await self._reset_timeout()
        except ClientError as e:
            _LOGGER.exception("Websocket disconnect error: %s", e)
        finally:
            _LOGGER.debug("Websocket disconnected")
            self._increase_failure()
            self._cancel_timeout()
            if self._ws_connection is not None and not self._ws_connection.closed:
                await self._ws_connection.close()
            if not session.closed:
                await session.close()
            self._ws_connection = None
            # make sure event does not timeout
            start_event.set()

    @property
    def has_recent_connect(self) -> bool:
        return time.monotonic() - RECENT_FAILURE_CUT_OFF <= self._last_connect

    @property
    def _should_reset_auth(self) -> bool:
        if self.has_recent_connect:
            if self._recent_failures > 2:
                return True
        else:
            self._recent_failures = 0
        return False

    def _increase_failure(self) -> None:
        if self.has_recent_connect:
            self._recent_failures += 1
        else:
            self._recent_failures = 1

    async def _do_timeout(self) -> bool:
        _LOGGER.debug("WS timed out")
        return await self.reconnect()

    async def _timeout_loop(self) -> None:
        while True:
            now = time.monotonic()
            if now > self._timeout:
                _LOGGER.debug("WS timed out")
                if not await self.reconnect():
                    _LOGGER.debug("WS could not reconnect")
                    continue
            sleep_time = self._timeout - now
            _LOGGER.debug("WS Timeout loop sleep %s", sleep_time)
            await asyncio.sleep(sleep_time)

    async def _reset_timeout(self) -> None:
        self._timeout = time.monotonic() + self.timeout_interval

        if self._timer_task is None:
            self._timer_task = asyncio.create_task(self._timeout_loop())

    def _cancel_timeout(self) -> None:
        if self._timer_task:
            self._timer_task.cancel()

    async def connect(self) -> bool:
        """Connect the websocket."""

        if self._connect_lock.locked():
            _LOGGER.debug("Another connect is already happening")
            return False
        try:
            await asyncio.wait_for(self._connect_lock.acquire(), timeout=0.1)
        except asyncio.TimeoutError:
            _LOGGER.debug("Failed to get connection lock")

        start_event = asyncio.Event()
        _LOGGER.debug("Scheduling WS connect...")
        asyncio.create_task(self._websocket_loop(start_event))

        try:
            await asyncio.wait_for(start_event.wait(), timeout=self.timeout_interval)
        except asyncio.TimeoutError:
            _LOGGER.warning("Timed out while waiting for Websocket to connect")
            await self.disconnect()

        self._connect_lock.release()
        if self._ws_connection is None:
            _LOGGER.debug("Failed to connect to Websocket")
            return False
        _LOGGER.debug("Connected to Websocket successfully")
        self._last_connect = time.monotonic()
        return True

    async def disconnect(self) -> None:
        """Disconnect the websocket."""

        _LOGGER.debug("Disconnecting websocket...")
        if self._ws_connection is None:
            return
        await self._ws_connection.close()
        self._ws_connection = None

    async def reconnect(self) -> bool:
        """Reconnect the websocket."""

        _LOGGER.debug("Reconnecting websocket...")
        await self.disconnect()
        await asyncio.sleep(self.backoff)
        return await self.connect()

    def subscribe(self, ws_callback: Callable[[WSMessage], None]) -> Callable[[], None]:
        """
        Subscribe to raw websocket messages.

        Returns a callback that will unsubscribe.
        """

        def _unsub_ws_callback() -> None:
            self._ws_subscriptions.remove(ws_callback)

        _LOGGER.debug("Adding subscription: %s", ws_callback)
        self._ws_subscriptions.append(ws_callback)
        return _unsub_ws_callback
