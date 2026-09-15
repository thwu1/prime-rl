
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y gcc g++ python3-pip jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/include

COPY pips_prefetcher.cc /app/pips_prefetcher.cc
COPY champsim.h /app/include/champsim.h
COPY cache.h /app/include/cache.h
COPY ooo_cpu.h /app/include/ooo_cpu.h
COPY memory_class.h /app/include/memory_class.h
COPY ipc1_rules.txt /app/ipc1_rules.txt

WORKDIR /app
