
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    openssl \
    zip \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install bcrypt==4.2.1

COPY setup_engagement.py /tmp/setup_engagement.py
RUN python3 /tmp/setup_engagement.py && rm /tmp/setup_engagement.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    john \
    hashcat \
    python3 \
    python3-pip \
    openssl \
    zip \
    unzip \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/engagement /app/engagement
RUN mkdir -p /app/results
WORKDIR /app
