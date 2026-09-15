
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    binutils \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/cipher_impl

COPY sbox_tables.c /tmp/sbox_tables.c
COPY sbox.h /app/cipher_impl/sbox.h
COPY audit_note.txt /app/cipher_impl/audit_note.txt

RUN gcc -c -o /app/cipher_impl/sbox.o /tmp/sbox_tables.c && rm /tmp/sbox_tables.c

WORKDIR /app
