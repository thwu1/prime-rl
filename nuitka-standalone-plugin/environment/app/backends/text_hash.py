"""Text hash processor using native C library via ctypes."""
import ctypes
import os

_app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_lib_path = os.path.join(_app_root, "native", "libhashutil.so")
_lib = ctypes.CDLL(_lib_path)

_lib.hash_hex.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
_lib.hash_hex.restype = None


def process(text):
    """Compute DJB2 hash of the text using native C library."""
    buf = ctypes.create_string_buffer(32)
    _lib.hash_hex(text.encode("utf-8"), buf, 32)
    return "hash=" + buf.value.decode("ascii")
