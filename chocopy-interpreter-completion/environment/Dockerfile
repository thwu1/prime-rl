FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    make \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/runtime /app/programs /app/build

COPY runtime/ /app/runtime/
COPY programs/ /app/programs/
COPY chocopy_partial.py /app/chocopy_partial.py
COPY Makefile /app/Makefile

WORKDIR /app
