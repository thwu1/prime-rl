#!/usr/bin/env python3
"""
Instrument parser.c with MAGMA canary calls and MAGMA_ENABLE_FIXES guards
for all five vulnerabilities (IMG001-IMG005).
"""


def instrument():
    path = "/app/src/parser.c"
    with open(path, "r") as f:
        src = f.read()

    # ---------------------------------------------------------------
    # Add magma.h include (after parser.h include)
    # ---------------------------------------------------------------
    src = src.replace(
        '#include "parser.h"',
        '#include "parser.h"\n#include "magma.h"',
    )

    # ---------------------------------------------------------------
    # IMG001: Integer overflow in parse_header
    # The per-dimension validation in validate_dimensions does NOT
    # prevent overflow in the product width*height*channels.
    # Trigger: the true 64-bit product exceeds UINT32_MAX.
    # ---------------------------------------------------------------
    src = src.replace(
        "    uint32_t buf_size = img->width * img->height * img->channels;\n"
        "    img->pixels = (uint8_t *)malloc(buf_size ? buf_size : 1);",

        "#ifdef MAGMA_ENABLE_CANARIES\n"
        "    MAGMA_LOG(IMG001, (uint64_t)img->width * img->height * img->channels > UINT32_MAX);\n"
        "#endif\n"
        "\n"
        "#ifdef MAGMA_ENABLE_FIXES\n"
        "    {\n"
        "        uint64_t safe_size = (uint64_t)img->width * img->height * img->channels;\n"
        "        if (safe_size > UINT32_MAX) return -1;\n"
        "    }\n"
        "#endif\n"
        "    uint32_t buf_size = img->width * img->height * img->channels;\n"
        "    img->pixels = (uint8_t *)malloc(buf_size ? buf_size : 1);",
    )

    # ---------------------------------------------------------------
    # IMG002: Off-by-one in apply_palette
    # CWE-193: the bounds check uses <= instead of <.
    # Trigger: idx equals palette_count (one past the last valid index).
    # ---------------------------------------------------------------
    src = src.replace(
        "        if (idx <= img->palette_count) {",

        "#ifdef MAGMA_ENABLE_CANARIES\n"
        "        MAGMA_LOG(IMG002, idx == img->palette_count);\n"
        "#endif\n"
        "\n"
        "#ifdef MAGMA_ENABLE_FIXES\n"
        "        if (idx < img->palette_count) {\n"
        "#else\n"
        "        if (idx <= img->palette_count) {\n"
        "#endif",
    )

    # ---------------------------------------------------------------
    # IMG003: Signed/unsigned comparison in apply_offsets
    # CWE-195: int32_t off compared with uint16_t pixel_count.
    # C promotion rules make negative offsets pass the check.
    # Trigger: offset is negative.
    # ---------------------------------------------------------------
    src = src.replace(
        "        if (off < pixel_count) {",

        "#ifdef MAGMA_ENABLE_CANARIES\n"
        "        MAGMA_LOG(IMG003, off < 0);\n"
        "#endif\n"
        "\n"
        "#ifdef MAGMA_ENABLE_FIXES\n"
        "        if (off >= 0 && off < (int32_t)pixel_count) {\n"
        "#else\n"
        "        if (off < pixel_count) {\n"
        "#endif",
    )

    # ---------------------------------------------------------------
    # IMG004: Missing length validation in parse_offsets
    # CWE-120: count entries read without checking chunk has enough data.
    # Compound trigger: count > 0 AND 2 + count*4 > chunk_len.
    # Uses MAGMA_AND to avoid coverage leakage from short-circuit &&.
    # ---------------------------------------------------------------
    src = src.replace(
        "    img->offsets = (int32_t *)malloc(count * sizeof(int32_t));",

        "#ifdef MAGMA_ENABLE_CANARIES\n"
        "    MAGMA_LOG(IMG004, MAGMA_AND(count > 0, 2 + (uint32_t)count * 4 > chunk_len));\n"
        "#endif\n"
        "\n"
        "#ifdef MAGMA_ENABLE_FIXES\n"
        "    if (count > 0 && 2 + (uint32_t)count * 4 > chunk_len) return -1;\n"
        "#endif\n"
        "    img->offsets = (int32_t *)malloc(count * sizeof(int32_t));",
    )

    # ---------------------------------------------------------------
    # IMG005: RLE decompression overflow in apply_rle
    # CWE-787: initial write_pos check passes but accumulated runs
    # exceed the pixel buffer boundary.
    # Trigger: write_pos + run_len > pixel_buf_size.
    # Fix: break out of the loop when overflow would occur.
    # ---------------------------------------------------------------
    src = src.replace(
        "        for (uint8_t j = 0; j < run_len; j++) {\n"
        "            img->pixels[write_pos] = value;\n"
        "            write_pos++;\n"
        "        }",

        "#ifdef MAGMA_ENABLE_CANARIES\n"
        "        MAGMA_LOG(IMG005, write_pos + run_len > pixel_buf_size);\n"
        "#endif\n"
        "\n"
        "#ifdef MAGMA_ENABLE_FIXES\n"
        "        if (write_pos + run_len > pixel_buf_size) break;\n"
        "#endif\n"
        "        for (uint8_t j = 0; j < run_len; j++) {\n"
        "            img->pixels[write_pos] = value;\n"
        "            write_pos++;\n"
        "        }",
    )

    with open(path, "w") as f:
        f.write(src)

    print("Instrumented parser.c with MAGMA canaries for IMG001-IMG005")


if __name__ == "__main__":
    instrument()
