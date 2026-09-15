
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y gcc libc6-dev && rm -rf /var/lib/apt/lists/*

COPY sb2_format.h /build/sb2_format.h
COPY sb2_parser.c /build/sb2_parser.c
COPY main.c /build/main.c

RUN gcc -O1 -fno-stack-protector -c /build/sb2_parser.c -o /build/sb2_parser.o -I/build
RUN gcc -O1 -fno-stack-protector /build/main.c /build/sb2_parser.o -o /build/firmware_sim -I/build

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gcc \
    libc6-dev \
    gdb \
    binutils \
    python3 \
    python3-pip \
    file \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /app/include /app/lib /app/docs

COPY --from=builder /build/firmware_sim /app/firmware_sim
COPY --from=builder /build/sb2_parser.o /app/lib/sb2_parser.o
COPY sb2_format.h /app/include/sb2_format.h
COPY main.c /app/src/main.c
COPY architecture.md /app/docs/architecture.md

RUN chmod +x /app/firmware_sim

WORKDIR /app
