import cairosvg
from PIL import Image
from io import BytesIO
from .config import RASTER_SIZE, BACKGROUND_COLOR


def rasterize(svg_string, size=RASTER_SIZE):
    """Rasterize an SVG string to an RGB PIL Image.

    Returns a solid white image on any failure.
    """
    try:
        png_bytes = cairosvg.svg2png(
            bytestring=svg_string.encode("utf-8"),
            output_width=size,
            output_height=size,
            background_color=BACKGROUND_COLOR,
        )
        return Image.open(BytesIO(png_bytes)).convert("RGB")
    except Exception:
        return Image.new("RGB", (size, size), (255, 255, 255))
