FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    make \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src

COPY ["src/opcode_def.h", "/app/src/opcode_def.h"]
COPY ["src/verifier.c", "/app/src/verifier.c"]
COPY ["src/optimizer.c", "/app/src/optimizer.c"]
COPY ["src/bcdump.c", "/app/src/bcdump.c"]
COPY ["src/Makefile", "/app/src/Makefile"]

WORKDIR /app
