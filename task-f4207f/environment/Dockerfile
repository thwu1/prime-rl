
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        python3 \
        python3-pip \
        wget \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set up app directory
RUN mkdir -p /app/tests

# Copy skeleton source files
COPY app_files/cpu6502.h /app/cpu6502.h
COPY app_files/cpu6502.c /app/cpu6502.c
COPY app_files/main.c /app/main.c
COPY app_files/Makefile /app/Makefile

# Copy cycle-test generator
COPY app_files/gen_cycle_tests.py /app/tests/gen_cycle_tests.py

# Download the Klaus2m5 functional test binary
RUN wget -q "https://raw.githubusercontent.com/Klaus2m5/6502_65C02_functional_tests/master/bin_files/6502_functional_test.bin" \
        -O /app/tests/6502_functional_test.bin

# Generate cycle-count test binaries
RUN cd /app/tests && python3 gen_cycle_tests.py

WORKDIR /app
