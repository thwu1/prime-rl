FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    g++ \
    universal-ctags \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/prefetchers /app/include

COPY prefetchers/FNLMMA_prefetcher.cc /app/prefetchers/FNLMMA_prefetcher.cc
COPY prefetchers/entangling_EPI_l1i_pref.cc /app/prefetchers/entangling_EPI_l1i_pref.cc
COPY prefetchers/PIPS_prefetcher.cc /app/prefetchers/PIPS_prefetcher.cc
COPY prefetchers/no_l1i_pref.cc /app/prefetchers/no_l1i_pref.cc

COPY include/champsim.h /app/include/champsim.h
COPY include/cache.h /app/include/cache.h
COPY include/ooo_cpu.h /app/include/ooo_cpu.h
COPY include/memory_class.h /app/include/memory_class.h

COPY rules.txt /app/rules.txt

WORKDIR /app
