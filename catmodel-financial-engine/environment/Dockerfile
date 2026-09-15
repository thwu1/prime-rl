FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip make sqlite3 && rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/data /app/docs

COPY data/fm_programme.csv /app/data/fm_programme.csv
COPY data/fm_profile.csv /app/data/fm_profile.csv
COPY data/fm_policytc.csv /app/data/fm_policytc.csv
COPY data/guls.csv /app/data/guls.csv
COPY docs/calcrules.md /app/docs/calcrules.md
COPY docs/fm_architecture.md /app/docs/fm_architecture.md

WORKDIR /app
