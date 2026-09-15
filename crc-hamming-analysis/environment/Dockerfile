FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 python3-pip gcc make xxd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY polynomials.json /app/polynomials.json
COPY FORMAT.md /app/FORMAT.md
COPY crc_engine.c /app/crc_engine.c
COPY Makefile /app/Makefile
COPY gen_test_data.py /tmp/gen_test_data.py

RUN python3 /tmp/gen_test_data.py && rm /tmp/gen_test_data.py

WORKDIR /app
