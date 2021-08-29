class UnifiProtectError(Exception):
    """Base class for all other Unifi Protect errors"""


class WSDecodeError(UnifiProtectError):
    """Exception raised when decoding Websocket packet"""


class ClientError(UnifiProtectError):
    """Base Class for all other Unifi Protect client errors"""


class Invalid(ClientError):
    """Invalid return from Authorization Request."""


class NotAuthorized(ClientError):
    """Wrong username and/or Password."""


class NvrError(ClientError):
    """Other error."""
