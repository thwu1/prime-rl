"""

Python ctypes bindings for libterminal.so -- VT/ANSI Terminal State Machine
"""
import ctypes
import json
import os


class CellStruct(ctypes.Structure):
    """Matches the C Cell typedef in terminal.h.

    Layout (x86_64, natural alignment):
      uint32_t codepoint    @ offset 0   (4 bytes)
      uint8_t  fg_r         @ offset 4   (1 byte)
      uint8_t  fg_g         @ offset 5   (1 byte)
      uint8_t  fg_b         @ offset 6   (1 byte)
      uint8_t  bg_r         @ offset 7   (1 byte)
      uint8_t  bg_g         @ offset 8   (1 byte)
      uint8_t  bg_b         @ offset 9   (1 byte)
      [2 bytes padding]     @ offset 10
      uint32_t attrs        @ offset 12  (4 bytes)
      Total: 16 bytes
    """
    _fields_ = [
        ('codepoint', ctypes.c_uint32),
        ('fg_r', ctypes.c_uint8),
        ('fg_g', ctypes.c_uint8),
        ('fg_b', ctypes.c_uint8),
        ('bg_r', ctypes.c_uint8),
        ('bg_g', ctypes.c_uint8),
        ('bg_b', ctypes.c_uint8),
        ('attrs', ctypes.c_uint32),
    ]


# Load the shared library
_lib = ctypes.CDLL('/app/libterminal.so')

# terminal_create(int width, int height) -> Terminal*
_lib.terminal_create.argtypes = [ctypes.c_int, ctypes.c_int]
_lib.terminal_create.restype = ctypes.c_void_p

# terminal_destroy(Terminal *term)
_lib.terminal_destroy.argtypes = [ctypes.c_void_p]
_lib.terminal_destroy.restype = None

# terminal_process(Terminal *term, const uint8_t *data, size_t len)
_lib.terminal_process.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_uint8),
    ctypes.c_size_t,
]
_lib.terminal_process.restype = None

# terminal_get_cell(const Terminal *term, int x, int y) -> Cell (by value)
_lib.terminal_get_cell.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
_lib.terminal_get_cell.restype = CellStruct

# terminal_get_cursor_x(const Terminal *term) -> int
_lib.terminal_get_cursor_x.argtypes = [ctypes.c_void_p]
_lib.terminal_get_cursor_x.restype = ctypes.c_int

# terminal_get_cursor_y(const Terminal *term) -> int
_lib.terminal_get_cursor_y.argtypes = [ctypes.c_void_p]
_lib.terminal_get_cursor_y.restype = ctypes.c_int


class TerminalEmulator:
    """High-level wrapper around the C terminal shared library."""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self._handle = _lib.terminal_create(width, height)
        if not self._handle:
            raise RuntimeError("terminal_create returned NULL")

    def process(self, data: bytes):
        buf = (ctypes.c_uint8 * len(data))(*data)
        _lib.terminal_process(self._handle, buf, len(data))

    def get_cell(self, x: int, y: int) -> dict:
        c = _lib.terminal_get_cell(self._handle, x, y)
        return {
            'cp': c.codepoint,
            'fg': [int(c.fg_r), int(c.fg_g), int(c.fg_b)],
            'bg': [int(c.bg_r), int(c.bg_g), int(c.bg_b)],
            'at': c.attrs,
        }

    def cursor(self) -> tuple:
        return (
            _lib.terminal_get_cursor_x(self._handle),
            _lib.terminal_get_cursor_y(self._handle),
        )

    def get_state(self) -> dict:
        cx, cy = self.cursor()
        cells = []
        for y in range(self.height):
            row = []
            for x in range(self.width):
                row.append(self.get_cell(x, y))
            cells.append(row)
        return {
            'cursor': {'x': cx, 'y': cy},
            'width': self.width,
            'height': self.height,
            'cells': cells,
        }

    def close(self):
        if self._handle:
            _lib.terminal_destroy(self._handle)
            self._handle = None

    def __del__(self):
        self.close()
