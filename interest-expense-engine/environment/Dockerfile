FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip make sqlite3 jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/regulations

COPY data/entities.csv /app/data/entities.csv
COPY data/financials.csv /app/data/financials.csv
COPY data/partnerships.csv /app/data/partnerships.csv
COPY data/ownership.csv /app/data/ownership.csv
COPY data/intercompany_loans.csv /app/data/intercompany_loans.csv
COPY data/distributions.csv /app/data/distributions.csv

COPY regulations/irc_163j.txt /app/regulations/irc_163j.txt
COPY regulations/cfr_163j_definitions.txt /app/regulations/cfr_163j_definitions.txt
COPY regulations/cfr_163j_partnerships.txt /app/regulations/cfr_163j_partnerships.txt
COPY regulations/cfr_385_3.txt /app/regulations/cfr_385_3.txt

WORKDIR /app
