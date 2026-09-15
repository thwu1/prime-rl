FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip libxml2-utils && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/models/case_001 /app/models/case_002 /app/models/case_003 /app/models/case_004

COPY case_001_model.xml /app/models/case_001/model.xml
COPY case_001_settings.txt /app/models/case_001/settings.txt

COPY case_002_model.xml /app/models/case_002/model.xml
COPY case_002_settings.txt /app/models/case_002/settings.txt

COPY case_003_model.xml /app/models/case_003/model.xml
COPY case_003_settings.txt /app/models/case_003/settings.txt

COPY case_004_model.xml /app/models/case_004/model.xml
COPY case_004_settings.txt /app/models/case_004/settings.txt

WORKDIR /app
