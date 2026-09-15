FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    nodejs \
    npm \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*


WORKDIR /app

COPY lib/sigil.js /app/lib/sigil.js
COPY plugins/sigil-persist.js /app/plugins/sigil-persist.js
COPY src/consumer.ts /app/src/consumer.ts
COPY src/negative.ts /app/src/negative.ts
COPY src/umd-global.ts /app/src/umd-global.ts
COPY src/plugin-consumer.ts /app/src/plugin-consumer.ts
COPY tsconfig.json /app/tsconfig.json
COPY package.json /app/package.json
