
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    clang \
    llvm \
    libbpf-dev \
    linux-libc-dev \
    python3-pip \
    binutils \
    && rm -rf /var/lib/apt/lists/*

COPY bpf_sources/ /tmp/bpf_sources/

RUN ln -sf /usr/include/$(uname -m)-linux-gnu/asm /usr/include/asm && \
    mkdir -p /app/samples && \
    clang -target bpf -O2 -g -c /tmp/bpf_sources/simple_xdp.bpf.c -o /app/samples/simple_xdp.o && \
    clang -target bpf -O2 -g -c /tmp/bpf_sources/icmp_filter.bpf.c -o /app/samples/icmp_filter.o && \
    clang -target bpf -O2 -g -c /tmp/bpf_sources/execve_monitor.bpf.c -o /app/samples/execve_monitor.o && \
    clang -target bpf -O2 -g -c /tmp/bpf_sources/tc_stats.bpf.c -o /app/samples/tc_stats.o && \
    clang -target bpf -O2 -g -c /tmp/bpf_sources/multi_probe.bpf.c -o /app/samples/multi_probe.o && \
    rm -rf /tmp/bpf_sources

RUN mkdir -p /app/reports

WORKDIR /app
