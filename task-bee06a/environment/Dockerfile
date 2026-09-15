FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3 gcc libssl-dev openssl && rm -rf /var/lib/apt/lists/*
COPY gen_evidence.py /tmp/gen_evidence.py
COPY exfiltool.c /tmp/exfiltool.c
RUN python3 /tmp/gen_evidence.py
RUN gcc -O2 -o /tmp/exfiltool /tmp/exfiltool.c -lcrypto && strip /tmp/exfiltool
RUN openssl enc -aes-256-cbc -pbkdf2 -salt -in /tmp/notes.txt -out /tmp/notes.enc -pass pass:AutumnT3mp3st

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y \
    python3-pip \
    tshark \
    openssl \
    binutils \
    xxd \
    file \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /app/evidence/workstation/.config /app/results
COPY --from=builder /tmp/traffic.pcap /app/evidence/traffic.pcap
COPY --from=builder /tmp/exfiltool /app/evidence/workstation/exfiltool
COPY --from=builder /tmp/bash_history /app/evidence/workstation/.bash_history
COPY --from=builder /tmp/notes.enc /app/evidence/workstation/.config/notes.enc
WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
