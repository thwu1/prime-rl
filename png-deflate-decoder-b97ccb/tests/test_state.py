
import ctypes
import os
import random
import subprocess

import pytest
from PIL import Image

DECODER = "/app/decode_png"
LIB_PATH = "/app/libdecode_png.so"


class PngImageC(ctypes.Structure):
    """ctypes mirror of the C PngImage struct from decode_png.h."""
    _fields_ = [
        ("pixels", ctypes.POINTER(ctypes.c_uint8)),
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("channels", ctypes.c_int),
    ]


def _load_lib():
    lib = ctypes.CDLL(LIB_PATH)
    lib.png_decode_file.argtypes = [
        ctypes.c_char_p, ctypes.POINTER(PngImageC)
    ]
    lib.png_decode_file.restype = ctypes.c_int
    lib.png_decode_memory.argtypes = [
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
        ctypes.POINTER(PngImageC),
    ]
    lib.png_decode_memory.restype = ctypes.c_int
    lib.png_free.argtypes = [ctypes.POINTER(PngImageC)]
    lib.png_free.restype = None
    return lib


def _decode_and_compare_cli(img, name, **save_kw):
    """Save image as PNG, run CLI decoder, compare output with PIL reference."""
    png = f"/tmp/tb_{name}.png"
    raw = f"/tmp/tb_{name}.raw"

    img.save(png, **save_kw)

    r = subprocess.run(
        [DECODER, png, raw], capture_output=True, timeout=30
    )
    assert r.returncode == 0, (
        f"Decoder exited {r.returncode}: {r.stderr.decode()[:500]}"
    )

    with open(raw, "rb") as fh:
        got = fh.read()

    want = img.tobytes()
    assert len(got) == len(want), (
        f"Size mismatch: got {len(got)} bytes, expected {len(want)}"
    )

    if got != want:
        idx = next(i for i, (a, b) in enumerate(zip(got, want)) if a != b)
        pytest.fail(
            f"Pixel mismatch at byte {idx}: got 0x{got[idx]:02x}, "
            f"want 0x{want[idx]:02x}"
        )


def _decode_file_via_lib(lib, png_path, expected_img):
    """Decode via library png_decode_file and compare."""
    img_out = PngImageC()
    ret = lib.png_decode_file(png_path.encode(), ctypes.byref(img_out))
    assert ret == 0, f"Library png_decode_file failed for {png_path}"

    want = expected_img.tobytes()
    size = img_out.width * img_out.height * img_out.channels
    assert size == len(want), (
        f"Library size mismatch: {size} != {len(want)}"
    )
    got = ctypes.string_at(img_out.pixels, size)
    lib.png_free(ctypes.byref(img_out))

    if got != want:
        idx = next(i for i, (a, b) in enumerate(zip(got, want)) if a != b)
        pytest.fail(
            f"Library pixel mismatch at byte {idx}: got 0x{got[idx]:02x}, "
            f"want 0x{want[idx]:02x}"
        )


def _decode_memory_via_lib(lib, png_path, expected_img):
    """Decode via library png_decode_memory and compare."""
    with open(png_path, "rb") as f:
        data = f.read()
    buf = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)

    img_out = PngImageC()
    ret = lib.png_decode_memory(buf, len(data), ctypes.byref(img_out))
    assert ret == 0, f"Library png_decode_memory failed"

    want = expected_img.tobytes()
    size = img_out.width * img_out.height * img_out.channels
    assert size == len(want), (
        f"Library memory size mismatch: {size} != {len(want)}"
    )
    got = ctypes.string_at(img_out.pixels, size)
    lib.png_free(ctypes.byref(img_out))

    if got != want:
        idx = next(i for i, (a, b) in enumerate(zip(got, want)) if a != b)
        pytest.fail(
            f"Library memory pixel mismatch at byte {idx}: "
            f"got 0x{got[idx]:02x}, want 0x{want[idx]:02x}"
        )


# ---- Grayscale (color type 0) ----


class TestGrayscale:
    def test_solid(self):
        _decode_and_compare_cli(Image.new("L", (8, 8), 128), "g_solid")

    def test_gradient(self):
        img = Image.new("L", (16, 16))
        for y in range(16):
            for x in range(16):
                img.putpixel((x, y), (x * 16 + y) & 255)
        _decode_and_compare_cli(img, "g_grad")

    def test_tall(self):
        img = Image.new("L", (1, 200))
        for y in range(200):
            img.putpixel((0, y), y & 255)
        _decode_and_compare_cli(img, "g_tall")


# ---- RGB (color type 2) ----


class TestRGB:
    def test_solid(self):
        _decode_and_compare_cli(
            Image.new("RGB", (8, 8), (255, 0, 128)), "rgb_solid"
        )

    def test_gradient(self):
        img = Image.new("RGB", (32, 32))
        for y in range(32):
            for x in range(32):
                img.putpixel(
                    (x, y), (x * 8 & 255, y * 8 & 255, (x + y) * 4 & 255)
                )
        _decode_and_compare_cli(img, "rgb_grad")

    def test_large(self):
        """100x100 varied content -- exercises dynamic Huffman."""
        img = Image.new("RGB", (100, 100))
        for y in range(100):
            for x in range(100):
                r = (x * 3 + y * 7 + 13) & 255
                g = (x * 5 + y * 11 + 37) & 255
                b = (x * 7 + y * 3 + 53) & 255
                img.putpixel((x, y), (r, g, b))
        _decode_and_compare_cli(img, "rgb_large")

    def test_wide(self):
        img = Image.new("RGB", (200, 1))
        for x in range(200):
            img.putpixel((x, 0), (x & 255, (x * 3) & 255, (x * 7) & 255))
        _decode_and_compare_cli(img, "rgb_wide")


# ---- RGBA (color type 6) ----


class TestRGBA:
    def test_solid(self):
        _decode_and_compare_cli(
            Image.new("RGBA", (8, 8), (255, 128, 0, 200)), "rgba_solid"
        )

    def test_gradient(self):
        img = Image.new("RGBA", (24, 24))
        for y in range(24):
            for x in range(24):
                img.putpixel(
                    (x, y),
                    (
                        x * 10 & 255,
                        y * 10 & 255,
                        (x + y) * 5 & 255,
                        (255 - x * 10) & 255,
                    ),
                )
        _decode_and_compare_cli(img, "rgba_grad")

    def test_random(self):
        """Random RGBA -- high-entropy data stresses dynamic Huffman."""
        random.seed(456)
        img = Image.new("RGBA", (64, 48))
        for y in range(48):
            for x in range(64):
                img.putpixel(
                    (x, y),
                    tuple(random.randint(0, 255) for _ in range(4)),
                )
        _decode_and_compare_cli(img, "rgba_rnd")


# ---- Grayscale + Alpha (color type 4) ----


class TestGrayAlpha:
    def test_basic(self):
        img = Image.new("LA", (16, 16))
        for y in range(16):
            for x in range(16):
                img.putpixel((x, y), (x * 16 & 255, y * 16 & 255))
        _decode_and_compare_cli(img, "la_basic")


# ---- Edge cases ----


class TestEdge:
    def test_single_pixel(self):
        _decode_and_compare_cli(
            Image.new("RGB", (1, 1), (42, 99, 200)), "edge_1px"
        )

    def test_random_noise_rgb(self):
        """Pure random noise -- strong test for all filter + Huffman paths."""
        random.seed(123)
        img = Image.new("RGB", (50, 50))
        for y in range(50):
            for x in range(50):
                img.putpixel(
                    (x, y),
                    tuple(random.randint(0, 255) for _ in range(3)),
                )
        _decode_and_compare_cli(img, "edge_rnd")


# ---- Compression level variants ----


class TestCompressLevels:
    def test_stored(self):
        """compress_level=0 -> stored (uncompressed) DEFLATE blocks."""
        _decode_and_compare_cli(
            Image.new("RGB", (10, 10), (100, 150, 200)),
            "cl_stored",
            compress_level=0,
        )

    def test_fast(self):
        """compress_level=1 -- may use fixed Huffman."""
        img = Image.new("RGB", (16, 16))
        for y in range(16):
            for x in range(16):
                img.putpixel((x, y), (x * 16, y * 16, 128))
        _decode_and_compare_cli(img, "cl_fast", compress_level=1)

    def test_max(self):
        """compress_level=9 -- deep dynamic Huffman."""
        random.seed(789)
        img = Image.new("RGB", (80, 60))
        for y in range(60):
            for x in range(80):
                img.putpixel(
                    (x, y),
                    tuple(random.randint(0, 255) for _ in range(3)),
                )
        _decode_and_compare_cli(img, "cl_max", compress_level=9)


# ---- Library API tests (ctypes FFI) ----


class TestLibraryFile:
    """Test shared library file-based decode API via ctypes."""

    @pytest.fixture(autouse=True)
    def setup_lib(self):
        self.lib = _load_lib()

    def test_rgb_decode(self):
        """Library file decode for a random RGB image."""
        random.seed(555)
        img = Image.new("RGB", (40, 30))
        for y in range(30):
            for x in range(40):
                img.putpixel(
                    (x, y),
                    tuple(random.randint(0, 255) for _ in range(3)),
                )
        png = "/tmp/tb_lib_rgb.png"
        img.save(png)
        _decode_file_via_lib(self.lib, png, img)

    def test_rgba_decode(self):
        """Library file decode for an RGBA gradient image."""
        img = Image.new("RGBA", (20, 20))
        for y in range(20):
            for x in range(20):
                img.putpixel(
                    (x, y),
                    (x * 12 & 255, y * 12 & 255, (x + y) * 6 & 255, 200),
                )
        png = "/tmp/tb_lib_rgba.png"
        img.save(png)
        _decode_file_via_lib(self.lib, png, img)


class TestLibraryMemory:
    """Test shared library in-memory decode API via ctypes."""

    @pytest.fixture(autouse=True)
    def setup_lib(self):
        self.lib = _load_lib()

    def test_rgb_memory(self):
        """In-memory decode of a random RGB image."""
        random.seed(777)
        img = Image.new("RGB", (30, 25))
        for y in range(25):
            for x in range(30):
                img.putpixel(
                    (x, y),
                    tuple(random.randint(0, 255) for _ in range(3)),
                )
        png = "/tmp/tb_mem_rgb.png"
        img.save(png)
        _decode_memory_via_lib(self.lib, png, img)

    def test_grayscale_memory(self):
        """In-memory decode of a grayscale image."""
        img = Image.new("L", (50, 50))
        for y in range(50):
            for x in range(50):
                img.putpixel((x, y), (x * y) & 255)
        png = "/tmp/tb_mem_gray.png"
        img.save(png)
        _decode_memory_via_lib(self.lib, png, img)
