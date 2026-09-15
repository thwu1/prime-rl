FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    jq \
    openssl \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/input /app/output /app/reference

COPY config.json /app/config.json
COPY input/export.ndjson /app/input/export.ndjson
COPY input/patient-contained.json /app/input/patient-contained.json
COPY input/elderly-patient.json /app/input/elderly-patient.json
COPY input/partial-date-patient.json /app/input/partial-date-patient.json
COPY input/bundle.json /app/input/bundle.json
COPY reference/CryptoHashProcessor.cs /app/reference/CryptoHashProcessor.cs
COPY reference/DateShiftProcessor.cs /app/reference/DateShiftProcessor.cs
COPY reference/CryptoHashProcessorTests.cs /app/reference/CryptoHashProcessorTests.cs
COPY reference/DateShiftProcessorTests.cs /app/reference/DateShiftProcessorTests.cs
COPY reference/fhir_anonymization.md /app/reference/fhir_anonymization.md

WORKDIR /app
