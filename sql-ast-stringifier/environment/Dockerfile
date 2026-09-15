FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    nodejs \
    npm \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src
COPY ["app/package.json", "/app/package.json"]
COPY ["app/tsconfig.json", "/app/tsconfig.json"]
COPY ["app/src", "/app/src"]

WORKDIR /app
