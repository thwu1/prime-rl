FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /data /app

COPY generate_input.py /tmp/generate_input.py
RUN python3 /tmp/generate_input.py && rm /tmp/generate_input.py

COPY validate_output.py /usr/local/bin/validate-output
RUN chmod +x /usr/local/bin/validate-output

WORKDIR /app
