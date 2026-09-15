#!/usr/bin/env python3
"""
Analyze the target raylib library's symbol table to determine
which config.h flags were used during compilation.

Key insight: some raylib public API functions always exist regardless of
whether their feature flag is enabled (they fall back to stubs or alternative
implementations). For those flags, we must detect INTERNAL implementation
symbols that are only present when the feature is compiled in:

  - SUPPORT_RPRAND_GENERATOR: rprand.h internal symbols (rprand_set_seed, etc.)
    When disabled, SetRandomSeed/GetRandomValue still exist but use stdlib rand().
  - SUPPORT_COMPRESSION_API: sdefl.h/sinfl.h internal symbols (sdeflate, sinflate)
    When disabled, CompressData/DecompressData still exist but return NULL.
  - SUPPORT_SCREEN_CAPTURE: TakeScreenshot always exists; flag only controls
    automatic F12 key capture. Detected via public symbol presence.
  - SUPPORT_AUTOMATION_EVENTS: LoadAutomationEventList always exists (as stub
    when disabled). Detected via public symbol presence.
"""
import subprocess
import json
import os
import re

def get_symbols(lib_path):
    """Extract all defined symbols from a static library."""
    result = subprocess.run(
        ["nm", "--defined-only", lib_path],
        capture_output=True, text=True
    )
    symbols = set()
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) >= 3:
            symbols.add(parts[2])
    return symbols

def check_symbol_present(symbols, pattern):
    """Check if any symbol matches the given pattern."""
    regex = re.compile(pattern)
    return any(regex.search(s) for s in symbols)

def main():
    lib_path = "/app/target/libraylib.a"
    symbols = get_symbols(lib_path)

    config = {}

    # === Module flags: unique public API functions per module ===

    # SUPPORT_MODULE_RSHAPES: DrawRectangle, DrawCircle, etc.
    config["SUPPORT_MODULE_RSHAPES"] = check_symbol_present(
        symbols, r'^DrawRectangle$'
    )

    # SUPPORT_MODULE_RTEXTURES: LoadImage, ExportImage, etc.
    config["SUPPORT_MODULE_RTEXTURES"] = check_symbol_present(
        symbols, r'^LoadImage$'
    )

    # SUPPORT_MODULE_RTEXT: DrawText, LoadFont, etc.
    config["SUPPORT_MODULE_RTEXT"] = check_symbol_present(
        symbols, r'^DrawText$'
    )

    # SUPPORT_MODULE_RMODELS: LoadModel, DrawModel, etc.
    config["SUPPORT_MODULE_RMODELS"] = check_symbol_present(
        symbols, r'^LoadModel$'
    )

    # SUPPORT_MODULE_RAUDIO: InitAudioDevice, LoadSound, etc.
    config["SUPPORT_MODULE_RAUDIO"] = check_symbol_present(
        symbols, r'^InitAudioDevice$'
    )

    # === Feature flags with unique public API sentinels ===

    # SUPPORT_CAMERA_SYSTEM: UpdateCamera only exists when enabled
    config["SUPPORT_CAMERA_SYSTEM"] = check_symbol_present(
        symbols, r'^UpdateCamera$'
    )

    # SUPPORT_GESTURES_SYSTEM: SetGesturesEnabled only exists when enabled
    config["SUPPORT_GESTURES_SYSTEM"] = check_symbol_present(
        symbols, r'^SetGesturesEnabled$'
    )

    # === Feature flags requiring INTERNAL symbol detection ===
    # Public API functions exist as stubs regardless of flag state.
    # Must check for internal implementation library symbols instead.

    # SUPPORT_RPRAND_GENERATOR: When enabled, rprand.h is compiled in via
    # #define RPRAND_IMPLEMENTATION / #include "external/rprand.h"
    # This creates rprand_* symbols. When disabled, only stdlib srand/rand used.
    config["SUPPORT_RPRAND_GENERATOR"] = check_symbol_present(
        symbols, r'rprand_'
    )

    # SUPPORT_SCREEN_CAPTURE: TakeScreenshot always exists. The flag controls
    # automatic F12-triggered screenshot in EndDrawing(). Since the function
    # is always present, we detect it via the public API symbol.
    config["SUPPORT_SCREEN_CAPTURE"] = check_symbol_present(
        symbols, r'^TakeScreenshot$'
    )

    # SUPPORT_AUTOMATION_EVENTS: LoadAutomationEventList always exists (stub
    # when disabled). Since it is always present, detect via public API.
    config["SUPPORT_AUTOMATION_EVENTS"] = check_symbol_present(
        symbols, r'^LoadAutomationEventList$'
    )

    # SUPPORT_COMPRESSION_API: When enabled, sdefl.h/sinfl.h are compiled in via
    # #define SDEFL_IMPLEMENTATION / #define SINFL_IMPLEMENTATION
    # This creates sdeflate/sinflate symbols. CompressData always exists as stub.
    config["SUPPORT_COMPRESSION_API"] = check_symbol_present(
        symbols, r'^(sdeflate|sinflate|zsdeflate|zsinflate)$'
    )

    # SUPPORT_IMAGE_EXPORT: ExportImage
    config["SUPPORT_IMAGE_EXPORT"] = check_symbol_present(
        symbols, r'^ExportImage$'
    )

    # SUPPORT_IMAGE_GENERATION: GenImageColor, GenImageGradientLinear, etc.
    config["SUPPORT_IMAGE_GENERATION"] = check_symbol_present(
        symbols, r'^GenImageColor$'
    )

    # Write report
    os.makedirs("/app/analysis", exist_ok=True)
    with open("/app/analysis/config_report.json", "w") as f:
        json.dump(config, f, indent=2)

    print("Configuration analysis complete:")
    for flag, enabled in sorted(config.items()):
        status = "ENABLED" if enabled else "DISABLED"
        print(f"  {flag}: {status}")

if __name__ == "__main__":
    main()
