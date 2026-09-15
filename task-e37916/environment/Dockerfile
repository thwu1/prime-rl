
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    make \
    xxd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app /app/corrupted

COPY fs_spec.h /app/fs_spec.h
COPY Makefile /app/Makefile
COPY error_types.json /app/error_types.json
COPY gen_reference.py /tmp/gen_reference.py
COPY gen_corrupted.py /tmp/gen_corrupted.py
RUN python3 /tmp/gen_reference.py && python3 /tmp/gen_corrupted.py && rm /tmp/gen_reference.py /tmp/gen_corrupted.py

WORKDIR /app
