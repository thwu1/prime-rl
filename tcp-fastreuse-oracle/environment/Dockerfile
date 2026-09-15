FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/captures

COPY format.md /app/format.md
COPY captures/capture_01.strace /app/captures/capture_01.strace
COPY captures/capture_01.ss /app/captures/capture_01.ss
COPY captures/capture_02.strace /app/captures/capture_02.strace
COPY captures/capture_02.ss /app/captures/capture_02.ss
COPY captures/capture_03.strace /app/captures/capture_03.strace
COPY captures/capture_03.ss /app/captures/capture_03.ss

WORKDIR /app
