
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gcc g++ clang cmake m4 git flex \
    python3 python3-pip \
    jq coreutils \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/csmith-project/csmith.git /app/csmith-src

COPY example_large.c /app/example_large.c

WORKDIR /app
