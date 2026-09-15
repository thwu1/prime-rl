FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip libxml2-utils && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/scenarios /app/results /app/xml_returns /app/irs_reference

COPY scenarios/ /app/scenarios/
COPY irs_reference/ /app/irs_reference/
COPY output_schema.json /app/output_schema.json
COPY mef_schema.xsd /app/mef_schema.xsd

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 jsonschema==4.23.0
