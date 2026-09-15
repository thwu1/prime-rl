"""
BRC Engine - Python ctypes bindings for the BRC shared library.

"""

import ctypes
import os

SHARED_SHIFT = 2
_Py_IMMORTAL_REFCNT = 0xFFFFFFFF

_STATE_NAMES = {0: "default", 1: "weakrefs", 2: "queued", 3: "merged"}

# ---------------------------------------------------------------------------
# Load the C shared library
# ---------------------------------------------------------------------------

_dir = os.path.dirname(os.path.abspath(__file__))
_lib = ctypes.CDLL(os.path.join(_dir, "libbrc.so"))


# ---------------------------------------------------------------------------
# Mirror the C struct layout
# ---------------------------------------------------------------------------

class _CBRCObject(ctypes.Structure):
    _fields_ = [
        ("ob_tid",            ctypes.c_int64),
        ("ob_ref_local",      ctypes.c_uint32),
        ("ob_ref_shared",     ctypes.c_int64),
        ("deallocated",       ctypes.c_int32),
        ("dealloc_type",      ctypes.c_int32),
        ("state_transitions", ctypes.c_int32),
        ("is_immortal",       ctypes.c_int32),
    ]


# ---------------------------------------------------------------------------
# Declare C function signatures
# ---------------------------------------------------------------------------

_lib.brc_init.argtypes = [ctypes.POINTER(_CBRCObject), ctypes.c_int64]
_lib.brc_init.restype = None

_lib.brc_incref.argtypes = [ctypes.POINTER(_CBRCObject), ctypes.c_int64]
_lib.brc_incref.restype = None

_lib.brc_decref.argtypes = [ctypes.POINTER(_CBRCObject), ctypes.c_int64]
_lib.brc_decref.restype = ctypes.c_int

_lib.brc_immortalize.argtypes = [ctypes.POINTER(_CBRCObject)]
_lib.brc_immortalize.restype = None

_lib.brc_create_weakref.argtypes = [ctypes.POINTER(_CBRCObject)]
_lib.brc_create_weakref.restype = None

_lib.brc_process_queued.argtypes = [ctypes.POINTER(_CBRCObject)]
_lib.brc_process_queued.restype = None


# ---------------------------------------------------------------------------
# Python wrappers
# ---------------------------------------------------------------------------

class BRCObject:
    """Python-facing wrapper around a C-backed BRC object."""

    def __init__(self, obj_id, owner_tid):
        self.obj_id = obj_id
        self._c = _CBRCObject()
        _lib.brc_init(ctypes.byref(self._c), ctypes.c_int64(owner_tid))

    @property
    def ob_tid(self):
        return self._c.ob_tid

    @property
    def ob_ref_local(self):
        return self._c.ob_ref_local

    @property
    def ob_ref_shared(self):
        return self._c.ob_ref_shared

    @property
    def deallocated(self):
        return bool(self._c.deallocated)

    @property
    def dealloc_type(self):
        dt = self._c.dealloc_type
        if dt == 1:
            return "quick"
        elif dt == 2:
            return "merged"
        return None

    @property
    def state_transitions(self):
        return self._c.state_transitions

    @property
    def is_immortal(self):
        return bool(self._c.is_immortal)

    @property
    def state(self):
        return self._c.ob_ref_shared & 0x3

    @property
    def state_name(self):
        return _STATE_NAMES[self.state]

    @property
    def shared_count(self):
        return self._c.ob_ref_shared >> SHARED_SHIFT

    @property
    def total_refcount(self):
        if self.is_immortal:
            return None
        if self.state == 3:
            return self.shared_count
        return self.ob_ref_local + self.shared_count


class BRCSimulator:
    """Orchestrates BRC operations, delegating per-object work to C."""

    def __init__(self):
        self.objects = {}
        self.merge_queues = {}

    def create(self, tid, obj_id):
        obj = BRCObject(obj_id, tid)
        self.objects[obj_id] = obj
        return obj

    def incref(self, tid, obj_id):
        obj = self.objects[obj_id]
        _lib.brc_incref(ctypes.byref(obj._c), ctypes.c_int64(tid))

    def decref(self, tid, obj_id):
        obj = self.objects[obj_id]
        result = _lib.brc_decref(ctypes.byref(obj._c), ctypes.c_int64(tid))
        if result == 1:
            owner = obj.ob_tid
            if owner not in self.merge_queues:
                self.merge_queues[owner] = []
            self.merge_queues[owner].append(obj_id)

    def immortalize(self, obj_id):
        obj = self.objects[obj_id]
        _lib.brc_immortalize(ctypes.byref(obj._c))

    def create_weakref(self, obj_id):
        obj = self.objects[obj_id]
        _lib.brc_create_weakref(ctypes.byref(obj._c))

    def process_queue(self, tid):
        if tid not in self.merge_queues:
            return
        queue = self.merge_queues.pop(tid)
        for obj_id in queue:
            obj = self.objects[obj_id]
            _lib.brc_process_queued(ctypes.byref(obj._c))

    def get_result(self, obj_id):
        obj = self.objects[obj_id]
        if obj.is_immortal:
            total = None
        elif obj.deallocated:
            total = 0
        else:
            total = obj.total_refcount
        return {
            "alive": not obj.deallocated,
            "immortal": obj.is_immortal,
            "dealloc_type": obj.dealloc_type,
            "total_refcount": total,
            "state_transitions": obj.state_transitions,
            "final_state": obj.state_name,
        }

    def run_scenario(self, operations):
        for entry in operations:
            tid = entry["tid"]
            op = entry["op"]
            if op == "create":
                self.create(tid, entry["obj"])
            elif op == "incref":
                self.incref(tid, entry["obj"])
            elif op == "decref":
                self.decref(tid, entry["obj"])
            elif op == "immortalize":
                self.immortalize(entry["obj"])
            elif op == "create_weakref":
                self.create_weakref(entry["obj"])
            elif op == "process_queue":
                self.process_queue(tid)
        results = {}
        for obj_id in self.objects:
            results[obj_id] = self.get_result(obj_id)
        return results
