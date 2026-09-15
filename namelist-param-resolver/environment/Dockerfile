FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    xmlstarlet \
    jq \
    libxml2-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY namelist_defaults.xml /app/namelist_defaults.xml
COPY resolver.py /app/resolver.py
COPY eamxx_config.py /app/eamxx_config.py
COPY reference/ /app/reference/
