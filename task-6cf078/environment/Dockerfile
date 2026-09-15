FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    make \
    xxd \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/libcobs

COPY protocol_reference.md /app/protocol_reference.md
COPY schema.json /app/schema.json
COPY v2_delta.json /app/v2_delta.json
COPY incident_report.txt /app/incident_report.txt

COPY cobs_postcard.h /app/libcobs/cobs_postcard.h
COPY cobs_postcard.c /app/libcobs/cobs_postcard.c
COPY decode_capture.c /app/libcobs/decode_capture.c
COPY libcobs_Makefile /app/libcobs/Makefile

COPY buggy_decoder.py /app/buggy_decoder.py

COPY generate_capture.py /tmp/generate_capture.py
RUN python3 /tmp/generate_capture.py && rm /tmp/generate_capture.py

RUN cd /app && python3 buggy_decoder.py

WORKDIR /app
