FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3-pip \
        curl \
        jq \
        procps \
    && rm -rf /var/lib/apt/lists/*

COPY patient_data.json /app/patient_data.json
COPY fhir_server.py /app/fhir_server.py
COPY start_fhir.sh /app/start_fhir.sh

RUN chmod +x /app/start_fhir.sh

RUN mkdir -p /app/output

WORKDIR /app
