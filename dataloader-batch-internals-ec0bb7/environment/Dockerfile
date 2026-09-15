FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y nodejs npm python3-pip && rm -rf /var/lib/apt/lists/*

COPY package.json /app/package.json
COPY tsconfig.json /app/tsconfig.json
COPY jest.config.js /app/jest.config.js
COPY src/ /app/src/

WORKDIR /app

