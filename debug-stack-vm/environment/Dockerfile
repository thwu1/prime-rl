FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libc6-dev \
        make \
        python3 \
        python3-pip \
        xxd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Generate correct binary files and expected outputs using a known-correct
# encoder (independent of the buggy assembler). Deleted after use.
COPY gen_bins.py /tmp/gen_bins.py
RUN python3 /tmp/gen_bins.py && rm /tmp/gen_bins.py

# Copy ISA spec, buggy assembler, buggy emulator, and build system
COPY spec.md assembler.py emulator.c Makefile /app/

# Build the (buggy) emulator
RUN make all

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
