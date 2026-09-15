#!/usr/bin/env python3
"""
Robustly patch raylib config.h to disable specific flags.
Comments out the #define lines so the macros become truly undefined,
which works regardless of whether the source code checks them with
#if defined(FLAG) or #if FLAG.

NOTE: SUPPORT_SCREEN_CAPTURE and SUPPORT_AUTOMATION_EVENTS are intentionally
NOT disabled here. Their public API symbols (TakeScreenshot,
LoadAutomationEventList) always exist regardless of the flag state (as stubs
or alternative implementations), making them impossible to detect via symbol
analysis alone. They remain enabled for deterministic reverse-engineering.
"""
import re
import sys

FLAGS_TO_DISABLE = [
    "SUPPORT_MODULE_RAUDIO",
    "SUPPORT_MODULE_RMODELS",
    "SUPPORT_MODULE_RTEXT",
    "SUPPORT_CAMERA_SYSTEM",
    "SUPPORT_GESTURES_SYSTEM",
    "SUPPORT_RPRAND_GENERATOR",
    "SUPPORT_COMPRESSION_API",
    "SUPPORT_FILEFORMAT_BMP",
    "SUPPORT_FILEFORMAT_GIF",
    "SUPPORT_FILEFORMAT_QOI",
    "SUPPORT_FILEFORMAT_DDS",
    "SUPPORT_CLIPBOARD_IMAGE",
]

config_path = sys.argv[1]

with open(config_path, "r") as f:
    content = f.read()

for flag in FLAGS_TO_DISABLE:
    # Comment out the entire #define line so the macro is truly undefined.
    # This handles both "#define FLAG 1" and "#define FLAG" (no value) forms,
    # with any amount of leading whitespace.
    pattern = r"^(\s*)(#\s*define\s+" + re.escape(flag) + r"\b.*$)"
    content = re.sub(pattern, r"\1// \2", content, flags=re.MULTILINE)

with open(config_path, "w") as f:
    f.write(content)

print(f"Patched {config_path}: disabled {len(FLAGS_TO_DISABLE)} flags")
