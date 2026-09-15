FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip gcc && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/descriptions /app/docs /app/include/linux

COPY descriptions/dev_hwaccel.txt /app/descriptions/dev_hwaccel.txt
COPY descriptions/dev_hwaccel_debug.txt /app/descriptions/dev_hwaccel_debug.txt
COPY docs/syzlang_reference.md /app/docs/syzlang_reference.md
COPY docs/const_extraction.md /app/docs/const_extraction.md
COPY include/linux/types.h /app/include/linux/types.h
COPY include/linux/ioctl.h /app/include/linux/ioctl.h
COPY include/linux/hwaccel.h /app/include/linux/hwaccel.h

WORKDIR /app
