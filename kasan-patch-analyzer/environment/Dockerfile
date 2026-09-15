FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    patch \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/crash_reports /app/verification_data /app/patches /app/kernel_src

COPY crash_reports/ /app/crash_reports/
COPY verification_data/ /app/verification_data/
COPY patches/ /app/patches/
COPY kernel_src/ /app/kernel_src/

WORKDIR /app
