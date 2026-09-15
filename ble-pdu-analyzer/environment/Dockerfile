FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/captures /app/firmware /app/tools /app/logs

COPY gen_captures.py /tmp/gen_captures.py
RUN python3 /tmp/gen_captures.py && rm /tmp/gen_captures.py

COPY dissector.py /app/tools/dissector.py
COPY ble_config.h /app/firmware/ble_config.h
COPY capture_notes.txt /app/captures/capture_notes.txt
COPY nrf_error_log.txt /app/logs/nrf_error_log.txt

WORKDIR /app
