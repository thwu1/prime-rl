
# === Builder stage: compile PE sample and create memory dump ===
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y gcc-mingw-w64-x86-64 python3 && rm -rf /var/lib/apt/lists/*
COPY sample.c /tmp/sample.c
COPY create_dump.py /tmp/create_dump.py
COPY normalize_pe.py /tmp/normalize_pe.py
RUN x86_64-w64-mingw32-gcc -o /tmp/original.exe /tmp/sample.c -O1 -s
RUN python3 /tmp/normalize_pe.py /tmp/original.exe
RUN python3 /tmp/create_dump.py /tmp/original.exe /tmp/memory_dump.bin /tmp/dump_meta.json 0x00007FF700000000
RUN python3 -c "import hashlib; print(hashlib.sha256(open('/tmp/original.exe','rb').read()).hexdigest())" > /tmp/original_hash.txt

# === Runtime stage: task environment only ===
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip xxd radare2 binutils-mingw-w64-x86-64 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/samples /app/output /app/.meta
COPY --from=builder /tmp/memory_dump.bin /app/samples/memory_dump.bin
COPY --from=builder /tmp/dump_meta.json /app/samples/dump_meta.json
COPY --from=builder /tmp/original_hash.txt /app/.meta/expected_hash.txt
WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 pefile==2024.8.26
