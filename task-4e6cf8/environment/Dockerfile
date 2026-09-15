FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    xxd \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Litestream v0.3.13 for replication validation
RUN curl -fsSL https://github.com/benbjohnson/litestream/releases/download/v0.3.13/litestream-v0.3.13-linux-amd64.deb -o /tmp/litestream.deb \
    && dpkg -i /tmp/litestream.deb \
    && rm /tmp/litestream.deb

RUN mkdir -p /app/data

COPY setup_data.py /tmp/setup_data.py
RUN python3 /tmp/setup_data.py && rm /tmp/setup_data.py

WORKDIR /app
