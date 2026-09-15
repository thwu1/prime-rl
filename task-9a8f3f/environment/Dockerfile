FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    xxd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/firmware /app/reference /app/vectors

COPY firmware/types.rs /app/firmware/types.rs
COPY firmware/ser.rs /app/firmware/ser.rs
COPY firmware/deser.rs /app/firmware/deser.rs
COPY firmware/framing.rs /app/firmware/framing.rs
COPY schema.json /app/schema.json
COPY reference/cobs_ref.c /app/reference/cobs_ref.c

RUN gcc -O2 -Wall -o /app/reference/cobs_ref /app/reference/cobs_ref.c
RUN /app/reference/cobs_ref gen-vectors /app/vectors

