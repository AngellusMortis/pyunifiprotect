import asyncio
from collections.abc import Callable
import logging
from typing import Any, Coroutine, Dict, List, Optional

from aiohttp import ClientSession, ClientWebSocketResponse, WSMessage, WSMsgType

_LOGGER = logging.getLogger(__name__)
CALLBACK_TYPE = Callable[..., Coroutine[Any, Any, Optional[Dict[str, str]]]]


class Websocket:
    url: str
    verify: bool
    timeout: int
    reconnect_wait: int
    _auth: CALLBACK_TYPE

    _headers: Optional[Dict[str, str]] = None
    _timer_task: Optional[asyncio.TimerHandle] = None
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
        self.timeout = timeout
        self.reconnect_wait = reconnect_wait
        self.verify = verify
        self._auth = auth_callback  # type: ignore

    @property
    def is_connected(self) -> bool:
        """Is Websocket connected"""
        return self._ws_connection is not None

    def _get_session(self) -> ClientSession:  # pylint: disable=no-self-use
        # for testing, to make easier to mock
        return ClientSession()

    async def _process_message(self, msg: WSMessage) -> bool:
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
            await self._reset_timeout()
            async for msg in self._ws_connection:
                if not await self._process_message(msg):
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

    def _cancel_timeout(self) -> None:
        if self._timer_task:
            self._timer_task.cancel()

    async def _timeout(self) -> None:
        _LOGGER.debug("WS timed out")
        if not await self.reconnect():
            await self._timeout()

    async def _reset_timeout(self) -> None:
        _LOGGER.debug("WS timeout reset")
        self._cancel_timeout()
        loop = asyncio.get_running_loop()
        self._timer_task = loop.call_later(self.timeout, lambda: asyncio.create_task(self._timeout()))

    async def connect(self) -> bool:
        """Connect the websocket."""

        _LOGGER.debug("Scheduling WS connect...")
        asyncio.create_task(self._websocket_loop())
        await asyncio.sleep(1)
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
