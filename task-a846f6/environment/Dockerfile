
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/pages

COPY app/pages/dashboard.html /app/pages/dashboard.html
COPY app/pages/reports.html /app/pages/reports.html
COPY app/pages/registration.html /app/pages/registration.html
COPY app/pages/articles.html /app/pages/articles.html
COPY app/pages/gallery.html /app/pages/gallery.html
COPY app/pages/portal.html /app/pages/portal.html
COPY app/baseline_config.json /app/baseline_config.json
COPY app/report_schema.json /app/report_schema.json

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
