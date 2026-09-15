FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 \
    python3-pip \
    tshark \
    lsof \
    && rm -rf /var/lib/apt/lists/*

COPY app/ /app/

RUN mkdir -p /app/exploits/findings /app/captures

WORKDIR /app
