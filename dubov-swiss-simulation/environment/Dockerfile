FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    g++ \
    cmake \
    make \
    git \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/MichaelVShapiro/CPPDubovSystem.git /app/engine

COPY tournament_spec.json /app/tournament_spec.json

RUN mkdir -p /app/output /tmp/dubov_work

WORKDIR /app
