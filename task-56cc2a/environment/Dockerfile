FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip nasm binutils xxd && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY rom_format.md /app/rom_format.md
COPY division_context.md /app/division_context.md
COPY microcode_spec.md /app/microcode_spec.md
COPY simulator_skeleton.py /app/simulator.py
COPY rom_generator.py /tmp/rom_generator.py
RUN python3 /tmp/rom_generator.py && rm /tmp/rom_generator.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
