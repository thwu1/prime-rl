FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y gcc python3-pip wget ca-certificates && rm -rf /var/lib/apt/lists/*

# Download the emps.c decompressor source (agent must compile it)
RUN mkdir -p /app && wget -q -O /app/emps.c https://www.netlib.org/lp/data/emps.c

# Download compressed MPS benchmark problems (agent must decompress them)
RUN mkdir -p /app/compressed && cd /app/compressed && \
    wget -q https://www.netlib.org/lp/data/afiro && \
    wget -q https://www.netlib.org/lp/data/sc50b && \
    wget -q https://www.netlib.org/lp/data/kb2 && \
    wget -q https://www.netlib.org/lp/data/share2b && \
    wget -q https://www.netlib.org/lp/data/adlittle

WORKDIR /app
