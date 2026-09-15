FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Clone SDSL v3 header-only library with submodules
RUN git clone --depth 1 https://github.com/xxsds/sdsl-lite.git /opt/sdsl-lite && \
    cd /opt/sdsl-lite && \
    git submodule update --init --recursive

# Generate deterministic input data
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

# Provide working CMakeLists.txt (agent must create analyzer.cpp)
COPY CMakeLists.txt /app/CMakeLists.txt

WORKDIR /app
