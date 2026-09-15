
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip curl && \
    rm -rf /var/lib/apt/lists/* && \
    curl -fsSL https://nodejs.org/dist/v18.20.4/node-v18.20.4-linux-x64.tar.gz \
      | tar -xz -C /usr/local --strip-components=1

WORKDIR /app

COPY package.json /app/package.json
RUN npm install --production

COPY pipeline.js /app/pipeline.js
