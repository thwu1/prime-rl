FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    make \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY app/ /app/

WORKDIR /app

# Inject per-instance challenge parameters (randomized buffer sizes + token)
RUN python3 inject_challenge.py

# Generate valid test packets adapted to randomized parameters
RUN python3 gen_testdata.py

# Preserve randomized source as the "original" for verification
RUN cp -r src .orig_src

# Build normal and AddressSanitizer-instrumented binaries
RUN make all && make asan
