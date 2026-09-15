FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

# Remove system-installed PyYAML to prevent pip install conflicts at runtime
RUN rm -rf /usr/lib/python3*/dist-packages/yaml /usr/lib/python3*/dist-packages/_yaml* /usr/lib/python3*/dist-packages/PyYAML* || true

COPY generate_data.py /tmp/generate_data.py
COPY risk_assessor.py /tmp/risk_assessor.py
COPY certify.py /tmp/certify.py

RUN python3 /tmp/generate_data.py && \
    mkdir -p /app/tools && \
    cp /tmp/risk_assessor.py /app/tools/risk_assessor.py && \
    cp /tmp/certify.py /app/tools/certify.py && \
    chmod +x /app/tools/risk_assessor.py && \
    chmod +x /app/tools/certify.py && \
    rm -f /tmp/generate_data.py /tmp/risk_assessor.py /tmp/certify.py

WORKDIR /app
