FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    octave \
    && rm -rf /var/lib/apt/lists/*

COPY constants.json /app/constants.json
COPY gmat_scripts/ /app/gmat_scripts/
COPY validate_template.m /app/validate_template.m

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
