FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip jq graphviz && rm -rf /var/lib/apt/lists/*

COPY resolver /app/resolver
COPY forge_db /app/forge_db
COPY Puppetfile /app/Puppetfile
COPY Puppetfile.staging /app/Puppetfile.staging
COPY Puppetfile.conflict /app/Puppetfile.conflict
COPY Puppetfile.circular /app/Puppetfile.circular
COPY README.md /app/README.md
COPY spec /app/spec
COPY schema /app/schema

WORKDIR /app
