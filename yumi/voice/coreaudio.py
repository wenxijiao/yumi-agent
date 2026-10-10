"""Read the actual macOS output rate; PortAudio's device metadata may be stale.

This uses the public CoreAudio property API. It does not change the system's
selected devices, restart audio services, or close other applications.
"""

from __future__ import annotations

import ctypes as ct
import sys
from functools import lru_cache
from typing import NamedTuple


class OutputFormat(NamedTuple):
    rate: float
    bluetooth: bool


class _Address(ct.Structure):
    _fields_ = [("selector", ct.c_uint32), ("scope", ct.c_uint32), ("element", ct.c_uint32)]


def _fourcc(value):
    return int.from_bytes(value.encode("ascii"), "big")


@lru_cache(maxsize=1)
def _libraries():
    ca = ct.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
    cf = ct.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    ca.AudioObjectGetPropertyDataSize.argtypes = [
        ct.c_uint32,
        ct.POINTER(_Address),
        ct.c_uint32,
        ct.c_void_p,
        ct.POINTER(ct.c_uint32),
    ]
    ca.AudioObjectGetPropertyData.argtypes = [
        ct.c_uint32,
        ct.POINTER(_Address),
        ct.c_uint32,
        ct.c_void_p,
        ct.POINTER(ct.c_uint32),
        ct.c_void_p,
    ]
    cf.CFStringGetCString.argtypes = [ct.c_void_p, ct.c_void_p, ct.c_long, ct.c_uint32]
    cf.CFRelease.argtypes = [ct.c_void_p]
    cf.CFRelease.restype = None
    return ca, cf


def _property(obj, selector, kind=ct.c_uint32, *, scope="glob", array=False):
    ca, _ = _libraries()
    address = _Address(_fourcc(selector), _fourcc(scope), 0)
    size = ct.c_uint32()
    if ca.AudioObjectGetPropertyDataSize(obj, ct.byref(address), 0, None, ct.byref(size)):
        return None
    if size.value == 0:
        return [] if array else None
    if not array and size.value != ct.sizeof(kind):
        return None
    value = (kind * (size.value // ct.sizeof(kind)))() if array else kind()
    if ca.AudioObjectGetPropertyData(obj, ct.byref(address), 0, None, ct.byref(size), ct.byref(value)):
        return None
    return list(value) if array else value.value


def _name(device):
    ref = _property(device, "lnam", ct.c_void_p)
    if not ref:
        return None
    _, cf = _libraries()
    try:
        value = ct.create_string_buffer(2048)
        if cf.CFStringGetCString(ref, value, len(value), 0x08000100):  # UTF-8
            return value.value.decode("utf-8")
        return None
    finally:
        cf.CFRelease(ref)  # CoreAudio transfers ownership of this CFString.


def output_format(name: str) -> OutputFormat | None:
    if sys.platform != "darwin":
        return None
    try:
        matches = [
            device
            for device in _property(1, "dev#", array=True) or []
            if _property(device, "stm#", scope="outp", array=True) and _name(device) == name
        ]
        if len(matches) != 1:
            return None
        rate = _property(matches[0], "nsrt", ct.c_double)
        transport = _property(matches[0], "tran")
        if not rate:
            return None
        return OutputFormat(rate, transport in {_fourcc("blue"), _fourcc("blea")})
    except (OSError, ValueError, AttributeError):
        return None
