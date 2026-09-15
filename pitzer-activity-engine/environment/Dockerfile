FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 make && \
    rm -rf /var/lib/apt/lists/*


WORKDIR /app

COPY ion_parameters.sql /app/ion_parameters.sql
COPY solutions.json /app/solutions.json
COPY reference_data.csv /app/reference_data.csv
