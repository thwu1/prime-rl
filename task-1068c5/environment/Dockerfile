FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip gcc xxd && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/xv6-src

COPY fs.h /app/xv6-src/fs.h
COPY mkfs.c /app/xv6-src/mkfs.c
COPY log.c /app/xv6-src/log.c
COPY fs.c /app/xv6-src/fs.c

COPY gen_fs_image.py /tmp/gen_fs_image.py
RUN python3 /tmp/gen_fs_image.py && rm -f /tmp/gen_fs_image.py

WORKDIR /app
