FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*


WORKDIR /app

COPY package.json /app/package.json
COPY tsconfig.json /app/tsconfig.json
COPY build.mjs /app/build.mjs
COPY src/ /app/src/

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 | tail
