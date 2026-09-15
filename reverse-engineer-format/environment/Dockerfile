
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y build-essential wget binutils python3 && rm -rf /var/lib/apt/lists/*
COPY oracle.c /tmp/oracle.c
COPY rpack_spec.txt /tmp/rpack_spec.txt
RUN python3 -c "import zlib; open('/tmp/rpack_spec.bin','wb').write(zlib.compress(open('/tmp/rpack_spec.txt','rb').read()))"
RUN wget -q https://raw.githubusercontent.com/DaveGamble/cJSON/v1.7.18/cJSON.c -O /tmp/cJSON.c && \
    wget -q https://raw.githubusercontent.com/DaveGamble/cJSON/v1.7.18/cJSON.h -O /tmp/cJSON.h && \
    gcc -O2 -o /tmp/oracle /tmp/oracle.c /tmp/cJSON.c -I/tmp -lm && \
    strip /tmp/oracle && \
    objcopy --add-section .rpack_spec=/tmp/rpack_spec.bin --set-section-flags .rpack_spec=noload,readonly /tmp/oracle /tmp/oracle

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y \
    python3-pip \
    xxd \
    binutils \
    strace \
    ltrace \
    gdb \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /tmp/oracle /app/oracle
RUN chmod +x /app/oracle
WORKDIR /app
