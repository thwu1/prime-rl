FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    python3-pip \
    python3-dev \
    sqlite3 \
    openssl \
    xxd \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 -q

RUN mkdir -p /app

COPY verify.c /tmp/verify.c
RUN gcc -O2 -o /app/verify /tmp/verify.c -s && rm /tmp/verify.c

COPY generate_traces.py /tmp/generate_traces.py
RUN python3 /tmp/generate_traces.py && rm /tmp/generate_traces.py

WORKDIR /app
