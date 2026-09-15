
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        gcc \
        libc6-dev \
        zlib1g-dev \
        xxd \
        binutils \
        file \
        radare2 \
        binwalk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY vault_tool.c /tmp/vault_tool.c
RUN gcc -O2 -o /app/vault_tool /tmp/vault_tool.c -lz && \
    strip --strip-all /app/vault_tool && \
    rm /tmp/vault_tool.c

COPY generate_vault.py /tmp/generate_vault.py
RUN python3 /tmp/generate_vault.py main /app/archive.vault && \
    python3 /tmp/generate_vault.py test /app/test_extra.vault && \
    rm /tmp/generate_vault.py

COPY format_notes.txt /app/FORMAT_NOTES.txt

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
