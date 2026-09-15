#!/bin/bash

# Copy implementation and completed build config
cp /solution/allocator_impl.c /app/src/allocator.c
cp /solution/meson_complete.build /app/meson.build

# Build with Meson
cd /app
rm -rf builddir
meson setup builddir
ninja -C builddir
