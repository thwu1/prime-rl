FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY vm.c /build/vm.c
RUN gcc -O2 -o /build/vm /build/vm.c && strip /build/vm

COPY gen_candidates.py /build/gen_candidates.py
RUN python3 /build/gen_candidates.py

COPY gen_ciphertext.py /build/gen_ciphertext.py
RUN python3 /build/gen_ciphertext.py

# --- Final stage: only task artifacts, no generators or plaintext ---
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    binutils \
    gdb \
    xxd \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/vm /app/vm
COPY --from=builder /app/candidates /app/candidates
COPY --from=builder /app/encrypted.bin /app/encrypted.bin
COPY notes.txt /app/notes.txt

RUN chmod +x /app/vm

WORKDIR /app
