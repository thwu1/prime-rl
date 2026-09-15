
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gcc \
    squashfs-tools \
    cpio \
    gzip \
    python3 \
    && rm -rf /var/lib/apt/lists/*

COPY gateway.c /tmp/build/gateway.c
COPY gateway.conf /tmp/build/gateway.conf
COPY crypto_stub.c /tmp/build/crypto_stub.c
COPY diag.py /tmp/build/diag.py
COPY build_firmware.py /tmp/build/build_firmware.py

RUN gcc -O0 -no-pie -o /tmp/build/gateway /tmp/build/gateway.c

RUN gcc -shared -fPIC -o /tmp/build/crypto.so /tmp/build/crypto_stub.c

RUN mkdir -p /tmp/sqfs_root/lib /tmp/sqfs_root/scripts \
    && cp /tmp/build/crypto.so /tmp/sqfs_root/lib/ \
    && cp /tmp/build/diag.py /tmp/sqfs_root/scripts/ \
    && mksquashfs /tmp/sqfs_root /tmp/build/modules.sqfs -noappend -comp gzip

RUN mkdir -p /tmp/cpio_root/usr/bin /tmp/cpio_root/opt /tmp/cpio_root/var \
    && cp /tmp/build/gateway /tmp/cpio_root/usr/bin/gateway \
    && chmod 755 /tmp/cpio_root/usr/bin/gateway \
    && cp /tmp/build/modules.sqfs /tmp/cpio_root/opt/modules.sqfs \
    && echo "1.3.7" > /tmp/cpio_root/var/firmware_version

RUN cd /tmp/cpio_root && find . -print | sort | cpio -o -H newc > /tmp/build/firmware.cpio 2>/dev/null

RUN gzip -c /tmp/build/firmware.cpio > /tmp/build/firmware.gz

RUN python3 /tmp/build/build_firmware.py /tmp/build/firmware.gz /tmp/build/gateway.conf /tmp/build/firmware.bin

RUN mkdir -p /app && cp /tmp/build/firmware.bin /app/firmware.bin

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gcc \
    binutils \
    squashfs-tools \
    cpio \
    gzip \
    file \
    xxd \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/firmware.bin /app/firmware.bin

WORKDIR /app
