FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    g++ \
    make \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Store original source in a safe location unaffected by volume mounts
COPY app/ /opt/redis-src/

# Set up working directory with source files
RUN rm -rf /app && cp -a /opt/redis-src /app

# Verify the source compiles correctly
RUN cd /app && make && make clean

WORKDIR /app
