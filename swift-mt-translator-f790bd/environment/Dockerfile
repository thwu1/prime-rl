FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    libxml2-utils \
    xmlstarlet \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/reference/sample_pair /app/input /app/output

COPY reference/cbpr_translation_guide.txt /app/reference/cbpr_translation_guide.txt
COPY reference/cbpr_rules.txt /app/reference/cbpr_rules.txt
COPY reference/mt103_fields.txt /app/reference/mt103_fields.txt
COPY reference/field_mapping.txt /app/reference/field_mapping.txt
COPY reference/sample_pair/input.mt103 /app/reference/sample_pair/input.mt103
COPY reference/sample_pair/expected_output.xml /app/reference/sample_pair/expected_output.xml
COPY input/msg_basic.mt103 /app/input/msg_basic.mt103
COPY input/msg_stp_fx.mt103 /app/input/msg_stp_fx.mt103
COPY input/msg_full_chain.mt103 /app/input/msg_full_chain.mt103

WORKDIR /app
