FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip jq && \
    rm -rf /var/lib/apt/lists/*

COPY filecheck.py /app/filecheck.py
RUN chmod +x /app/filecheck.py
COPY filecheck_spec.md /app/filecheck_spec.md
COPY manifest.json /app/manifest.json
COPY test_inputs/ /app/test_inputs/

WORKDIR /app
