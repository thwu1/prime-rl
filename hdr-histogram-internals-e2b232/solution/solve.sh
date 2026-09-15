#!/usr/bin/env bash

set -euo pipefail

# Copy the complete implementations
cp /solution/HdrHistogramSolved.java /app/src/HdrHistogram.java
cp /solution/HistogramCodecSolved.java /app/src/HistogramCodec.java

# Fix the Makefile
python3 -c '
with open("/app/Makefile", "w") as f:
    f.write("SRCDIR = /app/src\n")
    f.write("CLASSDIR = /app/classes\n")
    f.write("SOURCES = $(wildcard $(SRCDIR)/*.java)\n")
    f.write("\n")
    f.write(".PHONY: all build verify clean\n")
    f.write("\n")
    f.write("all: verify\n")
    f.write("\n")
    f.write("build: $(SOURCES)\n")
    f.write("\t@mkdir -p $(CLASSDIR)\n")
    f.write("\tjavac -d $(CLASSDIR) $(SOURCES)\n")
    f.write("\n")
    f.write("verify: build\n")
    f.write("\tjava -cp $(CLASSDIR) HistogramCodec roundtrip\n")
    f.write("\n")
    f.write("clean:\n")
    f.write("\trm -rf $(CLASSDIR)\n")
'

# Build and verify
make -C /app clean
make -C /app all
