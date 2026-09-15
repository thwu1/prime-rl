FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 curl && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/results

RUN curl -sL "https://predictioncenter.org/download_area/CASP16/results/tables/CASP16_prot_domains.scores.csv" -o /app/data/casp16_prot_domains_scores.csv && [ $(wc -c < /app/data/casp16_prot_domains_scores.csv) -gt 13000000 ]

WORKDIR /app
