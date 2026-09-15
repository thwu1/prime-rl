FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip gcc && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
WORKDIR /app

COPY codec_buggy.py /app/codec.py
COPY nibble_pack.c /app/nibble_pack.c
COPY validate.py /app/validate.py
COPY gen_reference.py /tmp/gen_reference.py
RUN python3 /tmp/gen_reference.py && rm /tmp/gen_reference.py
