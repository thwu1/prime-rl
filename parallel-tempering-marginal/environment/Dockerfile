FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip g++ make wget ca-certificates && rm -rf /var/lib/apt/lists/*

RUN cd /opt && \
    wget -q https://github.com/stan-dev/cmdstan/releases/download/v2.35.0/cmdstan-2.35.0.tar.gz && \
    tar xf cmdstan-2.35.0.tar.gz && \
    rm cmdstan-2.35.0.tar.gz && \
    cd cmdstan-2.35.0 && \
    make build -j$(nproc)

ENV CMDSTAN=/opt/cmdstan-2.35.0

RUN mkdir -p /app

COPY model.stan /app/model.stan
COPY data.json /app/data.json

WORKDIR /app
