import asyncio
from collections.abc import Callable
import logging
import time
from typing import Any, Coroutine, Dict, List, Optional

from aiohttp import ClientSession, ClientWebSocketResponse, WSMessage, WSMsgType

_LOGGER = logging.getLogger(__name__)
CALLBACK_TYPE = Callable[..., Coroutine[Any, Any, Optional[Dict[str, str]]]]


class Websocket:
    url: str
    verify: bool
    timeout_interval: int
    reconnect_wait: int
    _auth: CALLBACK_TYPE
    _timeout: float

    _headers: Optional[Dict[str, str]] = None
    _timer_task: Optional[asyncio.Task[None]] = None
    _ws_subscriptions: List[Callable[[WSMessage], None]] = []
    _ws_connection: Optional[ClientWebSocketResponse] = None

    def __init__(
        self,
        url: str,
        auth_callback: CALLBACK_TYPE,
        timeout: int = 30,
        reconnect_wait: int = 10,
        verify: bool = True,
    ) -> None:
        self.url = url
        self.timeout_interval = timeout
        self.reconnect_wait = reconnect_wait
        self.verify = verify
        self._auth = auth_callback  # type: ignore
        self._timeout = time.monotonic()

    @property
    def is_connected(self) -> bool:
        """Is Websocket connected"""
        return self._ws_connection is not None

    def _get_session(self) -> ClientSession:  # pylint: disable=no-self-use
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

    async def _websocket_loop(self) -> None:
        _LOGGER.debug("Connecting WS to %s", self.url)
        self._headers = await self._auth()

        session = self._get_session()
        self._ws_connection = await session.ws_connect(self.url, ssl=self.verify, headers=self._headers)
        try:
            async for msg in self._ws_connection:
                if not self._process_message(msg):
                    break
                await self._reset_timeout()
        finally:
            _LOGGER.debug("Websocket disconnected")
            self._cancel_timeout()
            if not self._ws_connection.closed:
                await self._ws_connection.close()
                self._ws_connection = None
            if not session.closed:
                await session.close()

    async def _do_timeout(self) -> bool:
        _LOGGER.debug("WS timed out")
        return await self.reconnect()

    async def _timeout_loop(self) -> None:
        while True:
            now = time.monotonic()
            if now > self._timeout:
                _LOGGER.debug("WS timed out")
                if not await self.reconnect():
                    _LOGGER.debug("Could not reconnect")
                    continue
            await asyncio.sleep(self._timeout - now)

    async def _reset_timeout(self) -> None:
        _LOGGER.debug("WS timeout reset")
        self._timeout = time.monotonic() + self.timeout_interval

        if self._timer_task is None:
            self._timer_task = asyncio.create_task(self._timeout_loop())

    def _cancel_timeout(self) -> None:
        if self._timer_task:
            self._timer_task.cancel()

    async def connect(self) -> bool:
        """Connect the websocket."""

        _LOGGER.debug("Scheduling WS connect...")
        asyncio.create_task(self._websocket_loop())
        start_time = self._timeout
        connect_timeout = time.monotonic() + self.timeout_interval
        # wait for message to ensure it is connected
        while time.monotonic() < connect_timeout and start_time == self._timeout:
            await asyncio.sleep(0.1)
        if self._ws_connection is None:
            _LOGGER.warning("Failed to connect to Websocket")
            return False
        _LOGGER.info("Connected to Websocket successfully")
        return True

    async def disconnect(self) -> None:
        """Disconnect the websocket."""

        _LOGGER.debug("Disconnecting websocket...")
        if self._ws_connection is None:
            return
        await self._ws_connection.close()

    async def reconnect(self) -> bool:
        """Reconnect the websocket."""

        _LOGGER.debug("Reconnecting websocket...")
        await self.disconnect()
        await asyncio.sleep(self.reconnect_wait)
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
