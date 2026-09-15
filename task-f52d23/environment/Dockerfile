FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    cmake \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install tqec==0.2.0

RUN mkdir -p /app
WORKDIR /app
