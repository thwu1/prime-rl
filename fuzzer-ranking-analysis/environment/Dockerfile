
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    sqlite3 \
    r-base-dev \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN Rscript -e 'install.packages("jsonlite", repos="https://cloud.r-project.org")'

RUN mkdir -p /app/pipeline/tmp /app/experiment

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

COPY pipeline/ /app/pipeline/
RUN chmod +x /app/pipeline/run_analysis.sh
RUN cd /app && /app/pipeline/run_analysis.sh
