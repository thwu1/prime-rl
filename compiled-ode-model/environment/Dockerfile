
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y r-base r-base-dev gcc make python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN R -e "install.packages('deSolve', repos='https://cloud.r-project.org')"

RUN mkdir -p /app

COPY system_spec.md /app/system_spec.md
COPY robertson_ext.c /app/robertson_ext.c
COPY forcing_data.csv /app/forcing_data.csv
COPY template.R /app/template.R

WORKDIR /app
