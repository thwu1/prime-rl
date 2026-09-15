FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        libxml2-utils \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/schemas

COPY validator_initial.py /app/validator.py
COPY schemas/pacs.008.001.08.xsd /app/schemas/pacs.008.001.08.xsd
COPY schemas/pacs.008.001.09.xsd /app/schemas/pacs.008.001.09.xsd
COPY schemas/pacs.008.001.10.xsd /app/schemas/pacs.008.001.10.xsd

WORKDIR /app

