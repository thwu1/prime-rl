FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    nodejs \
    npm \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY data/tests-fhir-r4.xml /data/tests-fhir-r4.xml
COPY data/FHIRPath.g4 /data/FHIRPath.g4
COPY data/resources/ /data/resources/

WORKDIR /app
