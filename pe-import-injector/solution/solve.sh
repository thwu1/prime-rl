#!/bin/bash

# Compile PE samples from source using MinGW cross-compilers
mkdir -p /app/samples
i686-w64-mingw32-gcc -w -o /app/samples/hello32.exe /app/build_src/hello32.c
x86_64-w64-mingw32-gcc -w -o /app/samples/multi64.exe /app/build_src/multi64.c
i686-w64-mingw32-gcc -w -shared -o /app/samples/mathlib.dll /app/build_src/mathlib.c

# Install the PE import editor
cp /solution/pe_import_editor.py /app/pe_import_editor.py
