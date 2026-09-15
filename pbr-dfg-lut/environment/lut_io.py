"""DFGL binary format I/O utilities."""


import struct
import os

MAGIC = b"DFGL"


def write_lut(pixels, path, width, height, channels=3):
    """
    Write pixel data as a DFGL binary file.

    Args:
        pixels: flat list of float values (row-major, channel-interleaved)
        path: output file path
        width: LUT width in pixels
        height: LUT height in pixels
        channels: number of channels per pixel (default 3)
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<III", width, height, channels))
        f.write(struct.pack(f"<{len(pixels)}f", *pixels))


def read_lut(path):
    """
    Read a DFGL binary file.

    Returns:
        (width, height, channels, pixels_list)
    """
    with open(path, "rb") as f:
        magic = f.read(4)
        if magic != MAGIC:
            raise ValueError(f"Invalid magic: {magic!r}, expected {MAGIC!r}")
        width, height, channels = struct.unpack("<III", f.read(12))
        n = width * height * channels
        pixels = list(struct.unpack(f"<{n}f", f.read(n * 4)))
    return width, height, channels, pixels
