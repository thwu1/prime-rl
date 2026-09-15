FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    g++ \
    cmake \
    make \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY rotation_math.hpp /app/rotation_math.hpp
COPY rotation_math.cpp /app/rotation_math.cpp
COPY CMakeLists.txt /app/CMakeLists.txt

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
