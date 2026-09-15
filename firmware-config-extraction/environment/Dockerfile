
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    build-essential \
    python3-pip \
    radare2 \
    && rm -rf /var/lib/apt/lists/*

COPY firmware_vm.c /tmp/firmware_vm.c

RUN cd /tmp && \
    gcc -O1 -Wall -Wno-unused-result -o firmware firmware_vm.c && \
    strip --strip-all firmware && \
    mkdir -p /app && \
    mv firmware /app/firmware && \
    chmod 755 /app/firmware && \
    rm -f firmware_vm.c

WORKDIR /app
