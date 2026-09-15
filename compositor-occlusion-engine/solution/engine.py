
"""
Compositor engine — bridges libregion.so via ctypes.
"""

import ctypes
import os

_dir = os.path.dirname(os.path.abspath(__file__))
_lib = ctypes.CDLL(os.path.join(_dir, "libregion.so"))


class _Rect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int),
                ("w", ctypes.c_int), ("h", ctypes.c_int)]


class _WindowDef(ctypes.Structure):
    _fields_ = [("id", ctypes.c_int), ("x", ctypes.c_int), ("y", ctypes.c_int),
                ("w", ctypes.c_int), ("h", ctypes.c_int), ("z", ctypes.c_int)]


class _OwnedRect(ctypes.Structure):
    _fields_ = [("owner", ctypes.c_int), ("x", ctypes.c_int), ("y", ctypes.c_int),
                ("w", ctypes.c_int), ("h", ctypes.c_int)]


_MAX = 16384

_lib.rect_subtract.restype = ctypes.c_int
_lib.rect_subtract.argtypes = [_Rect, _Rect, ctypes.POINTER(_Rect), ctypes.c_int]

_lib.compute_visible_regions.restype = ctypes.c_int
_lib.compute_visible_regions.argtypes = [
    ctypes.c_int, ctypes.c_int,
    ctypes.POINTER(_WindowDef), ctypes.c_int,
    ctypes.POINTER(_OwnedRect), ctypes.c_int,
]

_lib.merge_regions.restype = ctypes.c_int
_lib.merge_regions.argtypes = [ctypes.POINTER(_Rect), ctypes.c_int]


def rect_subtract(base, occluder):
    out = (_Rect * 4)()
    n = _lib.rect_subtract(_Rect(*base), _Rect(*occluder), out, 4)
    return [(out[i].x, out[i].y, out[i].w, out[i].h) for i in range(n)]


def compute_visible_regions(screen_w, screen_h, windows):
    nw = len(windows)
    if nw == 0:
        return {"bg": [(0, 0, screen_w, screen_h)]}

    arr = (_WindowDef * nw)()
    for i, (wid, x, y, w, h, z) in enumerate(windows):
        arr[i] = _WindowDef(wid, x, y, w, h, z)

    out = (_OwnedRect * _MAX)()
    n = _lib.compute_visible_regions(screen_w, screen_h, arr, nw, out, _MAX)

    result = {}
    for i in range(n):
        key = "bg" if out[i].owner == -1 else out[i].owner
        result.setdefault(key, []).append(
            (out[i].x, out[i].y, out[i].w, out[i].h)
        )

    # Ensure all window ids have entries
    for wid, *_ in windows:
        if wid not in result:
            result[wid] = []
    if "bg" not in result:
        result["bg"] = []

    return result


def merge_regions(rects):
    if not rects:
        return []
    n = len(rects)
    arr = (_Rect * n)()
    for i, (x, y, w, h) in enumerate(rects):
        arr[i] = _Rect(x, y, w, h)
    new_n = _lib.merge_regions(arr, n)
    return [(arr[i].x, arr[i].y, arr[i].w, arr[i].h) for i in range(new_n)]


def compute_dirty_regions(old_regions, new_regions, screen_w, screen_h):
    all_owners = set(list(old_regions.keys()) + list(new_regions.keys()))
    dirty = []
    for owner in all_owners:
        old_rects = old_regions.get(owner, [])
        new_rects = new_regions.get(owner, [])
        for nrect in new_rects:
            remaining = [nrect]
            for orect in old_rects:
                next_remaining = []
                for r in remaining:
                    next_remaining.extend(rect_subtract(r, orect))
                remaining = next_remaining
            dirty.extend(remaining)
    return dirty
