FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    xxd \
    binutils \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/forensics /app/output

COPY generate_forensics.py /tmp/generate_forensics.py
RUN python3 /tmp/generate_forensics.py /app/forensics && \
    test -f /app/forensics/memory.bin && \
    test -f /app/forensics/kernel.elf && \
    test -f /app/forensics/crash_report.log && \
    test -f /app/forensics/security_policy.txt && \
    cp -r /app/forensics /opt/forensics-backup && \
    rm /tmp/generate_forensics.py

WORKDIR /app
