FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    libxml2-dev \
    libxslt1-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install lxml==5.3.0

COPY app/patient_record.xml /app/patient_record.xml
COPY app/validation_rules.xml /app/validation_rules.xml
COPY app/valuesets.json /app/valuesets.json
COPY app/validator.py /app/validator.py

WORKDIR /app
