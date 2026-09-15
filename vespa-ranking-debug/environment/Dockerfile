FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

COPY business_requirements.md /app/business_requirements.md
COPY proposals/ /app/proposals/
COPY application/ /app/application/

WORKDIR /app
