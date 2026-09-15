FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 jq make && rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/lib /app/data

COPY generate_data.py /app/generate_data.py
COPY pipeline.py /app/pipeline.py
COPY config.json /app/config.json
COPY Makefile /app/Makefile
COPY validate.sh /app/validate.sh
COPY report.py /app/report.py
COPY ["lib/__init__.py", "/app/lib/__init__.py"]
COPY ["lib/metrics.py", "/app/lib/metrics.py"]
COPY ["lib/binning.py", "/app/lib/binning.py"]
COPY ["lib/scaling.py", "/app/lib/scaling.py"]

RUN chmod +x /app/validate.sh

WORKDIR /app
