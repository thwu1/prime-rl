FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y gcc python3 && rm -rf /var/lib/apt/lists/*
COPY generate.py malware.c benign.c /tmp/build/
WORKDIR /tmp/build
RUN python3 generate.py && \
    gcc -O1 -fno-PIE -no-pie -fno-stack-protector -w -o malware malware.c && \
    gcc -O1 -o benign benign.c && \
    strip --strip-all malware && \
    strip --strip-all benign

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    binutils \
    gdb \
    radare2 \
    strace \
    ltrace \
    file \
    xxd \
    yara \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
COPY --from=builder /tmp/build/malware /app/malware_sample
COPY --from=builder /tmp/build/benign /app/benign_sample
COPY incident_note.txt /app/incident_note.txt
RUN chmod +x /app/malware_sample /app/benign_sample

WORKDIR /app
