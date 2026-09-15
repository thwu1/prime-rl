FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    sqlite3 \
    gnuplot-nox \
    make \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY mflow_verify.py /app/mflow_verify.py
COPY config.toml /app/config.toml
COPY expected_schema.json /app/expected_schema.json
COPY README.txt /app/README.txt
COPY Makefile /app/Makefile
COPY plot_convergence.gp /app/plot_convergence.gp
COPY extract_convergence.py /app/extract_convergence.py
COPY setup_db.py /tmp/setup_db.py

RUN python3 /tmp/setup_db.py && rm /tmp/setup_db.py

WORKDIR /app
