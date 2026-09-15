FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y \
    python3-pip \
    tshark \
    upx-ucl \
    yara \
    wget \
    curl \
    binutils \
    file \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/evidence /app/artifacts /app/detection

WORKDIR /app
