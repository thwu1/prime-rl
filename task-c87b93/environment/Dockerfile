
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip git && \
    rm -rf /var/lib/apt/lists/*

COPY app/ /app/

RUN cd /app && \
    git init && \
    git config user.email "dev@example.com" && \
    git config user.name "Developer" && \
    git add . && \
    git commit -m "CSS cascade resolver: selectors, specificity, cascade ordering"

WORKDIR /app
