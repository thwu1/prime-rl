
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder

RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /build
COPY gen_alpha.c gen_beta.c gen_gamma.c /build/

RUN gcc -O2 -o /build/gen_alpha /build/gen_alpha.c
RUN gcc -O2 -o /build/gen_beta /build/gen_beta.c
RUN gcc -O2 -o /build/gen_gamma /build/gen_gamma.c
RUN strip /build/gen_alpha /build/gen_beta /build/gen_gamma

RUN /build/gen_beta 123456789abcdef0fedcba9876543210 800 > /build/stream_1.bin
RUN /build/gen_gamma deadbeefcafebabe 800 > /build/stream_2.bin
RUN /build/gen_alpha a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6 800 > /build/stream_3.bin

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    binutils \
    gdb \
    gcc \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
COPY --from=builder /build/gen_alpha /build/gen_beta /build/gen_gamma /app/
COPY --from=builder /build/stream_1.bin /build/stream_2.bin /build/stream_3.bin /app/
COPY notes.txt /app/notes.txt

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
