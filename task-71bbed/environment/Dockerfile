FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y gcc python3 && rm -rf /var/lib/apt/lists/*
COPY challenge_src/ /tmp/build/
RUN cd /tmp/build && python3 gen_bytecode_alpha.py && gcc -O2 -o /tmp/crackme_alpha vm.c && strip /tmp/crackme_alpha
RUN cd /tmp/build && python3 gen_bytecode_beta.py && gcc -O2 -o /tmp/crackme_beta vm.c && strip /tmp/crackme_beta
RUN cd /tmp/build && gcc -O2 -o /tmp/vm_runner vm_runner.c && strip /tmp/vm_runner

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    radare2 \
    binutils \
    xxd \
    file \
    strace \
    ltrace \
    gdb \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /tmp/crackme_alpha /app/crackme_alpha
COPY --from=builder /tmp/crackme_beta /app/crackme_beta
COPY --from=builder /tmp/vm_runner /app/vm_runner
WORKDIR /app
