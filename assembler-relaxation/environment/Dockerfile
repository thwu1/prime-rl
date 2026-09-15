FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*
COPY ref_asm.c /tmp/ref_asm.c
RUN gcc -O2 -o /tmp/reference_asm /tmp/ref_asm.c && strip /tmp/reference_asm

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    xxd \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/samples

COPY --from=builder /tmp/reference_asm /app/reference_asm
RUN chmod +x /app/reference_asm

COPY isa_spec.md /app/isa_spec.md
COPY samples/basic.asm /app/samples/basic.asm
COPY samples/medium.asm /app/samples/medium.asm
COPY samples/complex.asm /app/samples/complex.asm
COPY samples/all_instructions.asm /app/samples/all_instructions.asm

WORKDIR /app
