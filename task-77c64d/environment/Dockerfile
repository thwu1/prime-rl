FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip libxml2-utils && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY schemas/ /app/schemas/
COPY domains/ /app/domains/
COPY submissions/ /app/submissions/
COPY change_log.txt /app/change_log.txt
COPY rules_summary.txt /app/rules_summary.txt
