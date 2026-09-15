FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


# Install task environment: ARM cross-tools for disassembly, Python for analysis
RUN apt-get update && apt-get install -y \
    python3-pip \
    binutils-arm-linux-gnueabihf \
    xxd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Generate task artifacts at build time
COPY gen_firmware.py /tmp/gen_firmware.py
RUN python3 /tmp/gen_firmware.py && rm /tmp/gen_firmware.py

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
