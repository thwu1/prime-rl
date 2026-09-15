#!/bin/bash
# Build a target raylib library with a custom (secret) config.h configuration.
# The agent must reverse-engineer which flags were used by analyzing symbols.

set -e

# Clone a second copy for building the target
cp -r /app/raylib /tmp/raylib-target
cd /tmp/raylib-target/src

# Patch config.h to disable specific modules and features using the robust
# Python patcher (handles any indentation/spacing across raylib versions)
python3 /tmp/patch_config.py config.h

# Build with RAYLIB_MODULE_AUDIO=FALSE and RAYLIB_MODULE_MODELS=FALSE
# This prevents the Makefile from compiling raudio.o and rmodels.o
make PLATFORM=PLATFORM_DESKTOP_GLFW RAYLIB_LIBTYPE=STATIC \
     RAYLIB_MODULE_AUDIO=FALSE RAYLIB_MODULE_MODELS=FALSE \
     -j$(nproc)

# Copy the target library and headers
mkdir -p /app/target
cp libraylib.a /app/target/libraylib.a
cp raylib.h /app/target/raylib.h
cp raymath.h /app/target/raymath.h
cp rlgl.h /app/target/rlgl.h
cp config.h /app/target/config.h.hidden

# Clean up build directory
rm -rf /tmp/raylib-target

echo "Target library built and placed at /app/target/"
