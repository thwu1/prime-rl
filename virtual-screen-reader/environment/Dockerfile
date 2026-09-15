
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /data/fixtures /app

COPY app/screen_reader.py /app/screen_reader.py
COPY app/screen_reader.py /data/screen_reader_stub.py
COPY app/fixtures/ /data/fixtures/

WORKDIR /app
