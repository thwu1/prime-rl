FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    iverilog \
    python3-pip \
    make \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /app/tb /app/programs

COPY src/ /app/src/
COPY tb/ /app/tb/
COPY programs/ /app/programs/
COPY Makefile /app/Makefile

WORKDIR /app
