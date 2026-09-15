
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Create working directories
RUN mkdir -p /app/warriors

# Copy the ICWS'94 standard reference
COPY icws94_excerpt.txt /app/icws94_standard.txt

# Copy the buggy MARS simulator
COPY mars_buggy.py /app/mars.py

# Copy test warrior files
COPY warriors/imp.red /app/warriors/imp.red
COPY warriors/dwarf.red /app/warriors/dwarf.red
COPY warriors/stone.red /app/warriors/stone.red
COPY warriors/scanner.red /app/warriors/scanner.red
COPY warriors/impring.red /app/warriors/impring.red
COPY warriors/arith.red /app/warriors/arith.red
COPY warriors/predec.red /app/warriors/predec.red
COPY warriors/splbomb.red /app/warriors/splbomb.red
COPY warriors/djnloop.red /app/warriors/djnloop.red
COPY warriors/postinc.red /app/warriors/postinc.red

WORKDIR /app
