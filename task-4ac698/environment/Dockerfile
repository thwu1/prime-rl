FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    clang \
    llvm \
    libbpf-dev \
    linux-libc-dev \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY src/ /app/src/

WORKDIR /app

RUN mkdir -p /app/programs && \
    clang -O2 -target bpf -I/usr/include/x86_64-linux-gnu -I/app/src -c /app/src/simple_pass.c -o /app/programs/simple_pass.o && \
    clang -O2 -target bpf -I/usr/include/x86_64-linux-gnu -I/app/src -c /app/src/packet_counter.c -o /app/programs/packet_counter.o && \
    clang -O2 -target bpf -I/usr/include/x86_64-linux-gnu -I/app/src -c /app/src/port_filter.c -o /app/programs/port_filter.o && \
    clang -O2 -target bpf -I/usr/include/x86_64-linux-gnu -I/app/src -c /app/src/icmp_echo.c -o /app/programs/icmp_echo.o
