FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    gcc \
    make \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /app/data /app/reference

COPY data/test_config.json /app/data/test_config.json
COPY data/market_quotes.csv /app/data/market_quotes.csv
COPY reference/blackformula.jl /app/reference/blackformula.jl
COPY reference/iteration.jl /app/reference/iteration.jl
COPY reference/README.txt /app/reference/README.txt

WORKDIR /app
