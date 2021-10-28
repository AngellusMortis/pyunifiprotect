"""Classes for decoding/encoding data from Unifi OS Websocket"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import struct
from typing import Optional, Type
import zlib

from pyunifiprotect.data.types import ProtectWSPayloadFormat
from pyunifiprotect.exceptions import WSDecodeError

WS_HEADER_SIZE = 8


@dataclass
class WSPacketFrameHeader:
    packet_type: int
    payload_format: int
    deflated: int
    unknown: int
    payload_size: int


class WSRawPacketFrame:
    data: bytes = b""
    position: int = 0
    header: Optional[WSPacketFrameHeader] = None
    payload_format: ProtectWSPayloadFormat = ProtectWSPayloadFormat.NodeBuffer
    is_deflated: bool = False
    length: int = 0

    def set_data_from_binary(self, data: bytes):
        self.data = data
        if self.header is not None and self.header.deflated:
            self.data = zlib.decompress(self.data)

    def get_binary_from_data(self) -> bytes:
        data = self.data
        if self.is_deflated:
            data = zlib.compress(data)

        return data

    @staticmethod
    def klass_from_format(format_raw=bytes):
        payload_format = ProtectWSPayloadFormat(format_raw)

        if payload_format == ProtectWSPayloadFormat.JSON:
            return WSJSONPacketFrame

        return WSRawPacketFrame

    @staticmethod
    def from_binary(data: bytes, position: int = 0, klass: Optional[Type[WSRawPacketFrame]] = None) -> WSRawPacketFrame:
        """Decode a unifi updates websocket frame."""
        # The format of the frame is
        # b: packet_type
        # b: payload_format
        # b: deflated
        # b: unknown
        # i: payload_size

        header_end = position + WS_HEADER_SIZE

        try:
            packet_type, payload_format, deflated, unknown, payload_size = struct.unpack(
                "!bbbbi", data[position:header_end]
            )
        except struct.error as e:
            raise WSDecodeError from e

        if klass is None:
            frame = WSRawPacketFrame.klass_from_format(payload_format)()
        else:
            frame = klass()
            frame.payload_format = ProtectWSPayloadFormat(payload_format)

        frame.header = WSPacketFrameHeader(
            packet_type=packet_type,
            payload_format=payload_format,
            deflated=deflated,
            unknown=unknown,
            payload_size=payload_size,
        )
        frame.length = WS_HEADER_SIZE + frame.header.payload_size
        frame.is_deflated = bool(frame.header.deflated)
        frame_end = header_end + frame.header.payload_size
        frame.set_data_from_binary(data[header_end:frame_end])

        return frame

    @property
    def packed(self):
        data = self.get_binary_from_data()
        header = struct.pack(
            "!bbbbi",
            self.header.packet_type,
            self.header.payload_format,
            self.header.deflated,
            self.header.unknown,
            len(data),
        )

        return header + data


class WSJSONPacketFrame(WSRawPacketFrame):
    data: dict = {}  # type: ignore
    payload_format: ProtectWSPayloadFormat = ProtectWSPayloadFormat.NodeBuffer

    def set_data_from_binary(self, data: bytes):
        if self.header is not None and self.header.deflated:
            data = zlib.decompress(data)

        self.data = json.loads(data)

    def get_binary_from_data(self) -> bytes:
        data = self.json.encode("utf-8")
        if self.is_deflated:
            data = zlib.compress(data)

        return data

    @property
    def json(self) -> str:
        return json.dumps(self.data)


class WSPacket:
    _raw: bytes
    _raw_encoded: Optional[str] = None

    _action_frame: Optional[WSRawPacketFrame] = None
    _data_frame: Optional[WSRawPacketFrame] = None

    def __init__(self, data: bytes):
        self._raw = data

    def decode(self):
        self._action_frame = WSRawPacketFrame.from_binary(self._raw)
        self._data_frame = WSRawPacketFrame.from_binary(self._raw, self._action_frame.length)

    @property
    def action_frame(self) -> WSRawPacketFrame:
        if self._action_frame is None:
            self.decode()

        if self._action_frame is None:
            raise WSDecodeError("Packet unexpectedly not decoded")

        return self._action_frame

    @property
    def data_frame(self) -> WSRawPacketFrame:
        if self._data_frame is None:
            self.decode()

        if self._data_frame is None:
            raise WSDecodeError("Packet unexpectedly not decoded")

        return self._data_frame

    @property
    def raw(self) -> bytes:
        return self._raw

    @raw.setter
    def raw(self, data: bytes):
        self._raw = data
        self._action_frame = None
        self._data_frame = None
        self._raw_encoded = None

    @property
    def raw_base64(self) -> str:
        if self._raw_encoded is None:
            self._raw_encoded = base64.b64encode(self._raw).decode("utf-8")

        return self._raw_encoded

    def pack_frames(self) -> bytes:
        self._raw_encoded = None
        self._raw = self.action_frame.packed + self.data_frame.packed

        return self._raw
