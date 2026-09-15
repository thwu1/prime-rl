FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip curl jq && \
    rm -rf /var/lib/apt/lists/*

# Install Node.js 20 LTS from official binary (includes npm, avoids broken apt npm)
RUN curl -fsSL https://nodejs.org/dist/v20.11.1/node-v20.11.1-linux-x64.tar.gz | \
    tar -xz -C /usr/local --strip-components=1

RUN mkdir -p /app/fixtures

COPY package.json /app/package.json
RUN cd /app && npm install

COPY wire_format.md /app/wire_format.md
COPY yjs_oracle.js /app/yjs_oracle.js

RUN cd /app && node yjs_oracle.js generate-fixtures

WORKDIR /app

