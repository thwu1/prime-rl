FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Download compressed Netlib LP benchmark problems (legacy encoding)
RUN mkdir -p /app/data && \
    curl -sfL -o /app/data/afiro https://www.netlib.org/lp/data/afiro && \
    curl -sfL -o /app/data/blend https://www.netlib.org/lp/data/blend && \
    curl -sfL -o /app/data/sc50a https://www.netlib.org/lp/data/sc50a && \
    curl -sfL -o /app/data/sc50b https://www.netlib.org/lp/data/sc50b && \
    curl -sfL -o /app/data/adlittle https://www.netlib.org/lp/data/adlittle && \
    curl -sfL -o /app/data/kb2 https://www.netlib.org/lp/data/kb2

# Verify downloads are non-empty
RUN test -s /app/data/afiro && \
    test -s /app/data/blend && \
    test -s /app/data/sc50a && \
    test -s /app/data/sc50b && \
    test -s /app/data/adlittle && \
    test -s /app/data/kb2

COPY spec.json /app/spec.json

WORKDIR /app
