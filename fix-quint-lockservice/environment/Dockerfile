FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    curl \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://nodejs.org/dist/v20.11.1/node-v20.11.1-linux-x64.tar.gz \
    | tar -xzf - -C /usr/local --strip-components=1

RUN npm install -g @informalsystems/quint@0.23.1

COPY lock_manager.qnt /app/lock_manager.qnt

WORKDIR /app
