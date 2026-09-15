#!/usr/bin/env python3
"""Initialize the WebGL conformance metadata database."""

import os
import sqlite3

DB_PATH = "/app/conformance.db"


def create_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)

    # Sampler type to texture target compatibility
    conn.execute(
        "CREATE TABLE format_compatibility ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  sampler_type TEXT NOT NULL,"
        "  texture_target INTEGER NOT NULL,"
        "  compatible INTEGER NOT NULL,"
        "  spec_section TEXT NOT NULL"
        ")"
    )

    TEXTURE_2D = 0x0DE1
    TEXTURE_CUBE_MAP = 0x8513

    conn.executemany(
        "INSERT INTO format_compatibility "
        "(sampler_type, texture_target, compatible, spec_section) "
        "VALUES (?, ?, ?, ?)",
        [
            ("sampler2D", TEXTURE_2D, 1, "GLES2_3.7.5"),
            ("sampler2D", TEXTURE_CUBE_MAP, 0, "GLES2_3.7.5"),
            ("samplerCube", TEXTURE_CUBE_MAP, 1, "GLES2_3.7.5"),
            ("samplerCube", TEXTURE_2D, 0, "GLES2_3.7.5"),
        ],
    )

    # Renderable format table
    conn.execute(
        "CREATE TABLE renderable_formats ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  internal_format INTEGER NOT NULL,"
        "  format_name TEXT NOT NULL,"
        "  attachment_type TEXT NOT NULL,"
        "  renderable INTEGER NOT NULL,"
        "  spec_section TEXT NOT NULL"
        ")"
    )

    RGBA4 = 0x8056
    RGB5_A1 = 0x8057
    RGB565 = 0x8D62
    DEPTH_COMPONENT16 = 0x81A5
    STENCIL_INDEX8 = 0x8D48
    RGBA = 0x1908
    RGB = 0x1907
    LUMINANCE = 0x1909
    LUMINANCE_ALPHA = 0x190A
    ALPHA = 0x1906

    conn.executemany(
        "INSERT INTO renderable_formats "
        "(internal_format, format_name, attachment_type, renderable, spec_section) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (RGBA4, "RGBA4", "color", 1, "GLES2_4.4.5"),
            (RGB5_A1, "RGB5_A1", "color", 1, "GLES2_4.4.5"),
            (RGB565, "RGB565", "color", 1, "GLES2_4.4.5"),
            (RGBA, "RGBA", "color_tex", 1, "WEBGL_1.0_6.6"),
            (RGB, "RGB", "color_tex", 1, "WEBGL_1.0_6.6"),
            (LUMINANCE, "LUMINANCE", "color_tex", 0, "WEBGL_1.0_6.6"),
            (LUMINANCE_ALPHA, "LUMINANCE_ALPHA", "color_tex", 0, "WEBGL_1.0_6.6"),
            (ALPHA, "ALPHA", "color_tex", 0, "WEBGL_1.0_6.6"),
            (DEPTH_COMPONENT16, "DEPTH_COMPONENT16", "depth", 1, "GLES2_4.4.5"),
            (STENCIL_INDEX8, "STENCIL_INDEX8", "stencil", 1, "GLES2_4.4.5"),
        ],
    )

    conn.commit()
    conn.close()
    print(f"Created conformance database at {DB_PATH}")


if __name__ == "__main__":
    create_db()
