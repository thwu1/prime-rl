FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/compact /app/tests

COPY compact_init.py /app/compact/__init__.py
COPY compact_codec.py /app/compact/codec.py
COPY compact_varint.py /app/compact/varint.py
COPY test_basic.py /app/tests/test_basic.py
RUN touch /app/tests/__init__.py

WORKDIR /app
