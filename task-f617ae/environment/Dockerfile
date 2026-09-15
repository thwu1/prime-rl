FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder

RUN apt-get update && apt-get install -y gcc python3 && rm -rf /var/lib/apt/lists/*

COPY vm_runner.c /build/vm_runner.c
COPY gen_reference.py /build/gen_reference.py
COPY gen_test_vectors.py /build/gen_test_vectors.py

WORKDIR /build
RUN gcc -O2 -s -o vm_runner vm_runner.c
RUN python3 gen_reference.py
RUN python3 gen_test_vectors.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    radare2 \
    gdb \
    binutils \
    xxd \
    strace \
    ltrace \
    file \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/vm_runner /app/vm_runner
COPY --from=builder /build/reference.bc /app/reference.bc
COPY --from=builder /build/test_vectors.json /app/test_vectors.json

RUN chmod +x /app/vm_runner

WORKDIR /app
