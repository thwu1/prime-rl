FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        g++ \
        make \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Copy server source code to /app
COPY app_src/ /app/

# Verify that the base server compiles
RUN cd /app && make clean && make && make clean

WORKDIR /app
