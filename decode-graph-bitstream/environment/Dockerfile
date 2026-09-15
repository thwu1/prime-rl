FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc cmake make jq xxd && \
    rm -rf /var/lib/apt/lists/*

COPY generate_data.py /tmp/generate_data.py
COPY notes.md /tmp/notes.md

COPY CMakeLists.txt /app/tools/CMakeLists.txt
COPY bitstream.h /app/tools/bitstream.h
COPY bitstream.c /app/tools/bitstream.c
COPY header_info.c /app/tools/header_info.c
COPY bitprobe.c /app/tools/bitprobe.c
COPY ef_dump.c /app/tools/ef_dump.c

RUN python3 /tmp/generate_data.py && \
    mv /tmp/notes.md /app/data/NOTES.md && \
    rm /tmp/generate_data.py

WORKDIR /app
