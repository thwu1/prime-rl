FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    cmake \
    python3-pip \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY CMakeLists.txt /app/CMakeLists.txt
COPY build_spec.json /app/build_spec.json
COPY build_errors.log /app/build_errors.log

WORKDIR /app
