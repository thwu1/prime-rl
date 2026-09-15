# Build stage - compile the vulnerable parser, source stays only here
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*
COPY fw_parser.c /tmp/fw_parser.c
RUN gcc -O1 -Wall -fno-stack-protector -o /tmp/fw_parser /tmp/fw_parser.c && \
    strip --strip-debug /tmp/fw_parser

# Final stage - task environment only
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    binutils \
    gdb \
    file \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/docs
COPY --from=builder /tmp/fw_parser /app/fw_parser
COPY sb2_format.md /app/docs/sb2_format.md
RUN chmod +x /app/fw_parser
WORKDIR /app
