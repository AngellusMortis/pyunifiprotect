"""Tests for pyunifiprotect.unifi_data"""

import base64
import json

import pytest

from pyunifiprotect.data import FixSizeOrderedDict, ProtectWSPayloadFormat
from pyunifiprotect.unifi_data import decode_ws_frame

PACKET_B64 = b"AQEBAAAAAHR4nB2MQQrCMBBFr1JmbSDNpJnRG4hrDzBNZqCgqUiriHh3SZb/Pd7/guRtWSucBtgfRTaFwwBV39c+zqUJskQW1DufUVwkJsfFxDGLyRFj0dSz+1r0dtFPa+rr2dDSD8YsyceUpskQxzjjHIIQMvz+hMoj/AIBAQAAAAA1eJyrViotKMnMTVWyUjA0MjawMLQ0MDDQUVDKSSwuCU5NzQOJmxkbACUszE0sLQ1rAVU/DPU="
PACKET_ACTION = {
    "action": "update",
    "newUpdateId": "7f67f2e0-0c3a-4787-8dfa-88afa934de6e",
    "modelKey": "nvr",
    "id": "1ca6046655f3314b3b22a738",
}
PACKET_DATA = {"uptime": 1230819000, "lastSeen": 1630081874991}


def test_decode_frame():
    packet_raw = base64.b64decode(PACKET_B64)

    raw_data, payload_format, position = decode_ws_frame(packet_raw, 0)

    assert json.loads(raw_data) == PACKET_ACTION
    assert payload_format == ProtectWSPayloadFormat.JSON
    assert position == 124

    raw_data, payload_format, position = decode_ws_frame(packet_raw, position)

    assert json.loads(raw_data) == PACKET_DATA
    assert payload_format == ProtectWSPayloadFormat.JSON
    assert position == 185


def test_fix_order_size_dict_no_max():
    d = FixSizeOrderedDict()
    d["test"] = 1
    d["test2"] = 2
    d["test3"] = 3

    del d["test2"]

    assert d == {"test": 1, "test3": 3}


def test_fix_order_size_dict_max():
    d = FixSizeOrderedDict(max_size=1)
    d["test"] = 1
    d["test2"] = 2
    d["test3"] = 3

    with pytest.raises(KeyError):
        del d["test2"]

    assert d == {"test3": 3}


def test_fix_order_size_dict_negative_max():
    d = FixSizeOrderedDict(max_size=-1)
    d["test"] = 1
    d["test2"] = 2
    d["test3"] = 3

    del d["test2"]

    assert d == {"test": 1, "test3": 3}
