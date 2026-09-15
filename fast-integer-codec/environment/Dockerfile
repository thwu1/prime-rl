
# Stage 1: Build reference binary from correct source, then discard source
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y gcc make && rm -rf /var/lib/apt/lists/*
COPY reference_src /tmp/ref_src
WORKDIR /tmp/ref_src
RUN make && strip -s libfastnum.so

# Stage 2: Runtime environment
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gcc \
    make \
    binutils \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Copy only the stripped reference binary (source is discarded with builder stage)
COPY --from=builder /tmp/ref_src/libfastnum.so /opt/reference/libfastnum_ref.so

# Copy buggy source to persistent location and /app
COPY app /opt/fastnum_src
RUN mkdir -p /app && cp -f /opt/fastnum_src/* /app/

# Copy hex encoding variant source files
COPY variants /opt/variants

WORKDIR /app
