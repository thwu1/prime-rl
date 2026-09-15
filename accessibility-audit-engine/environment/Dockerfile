FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install beautifulsoup4==4.12.3

RUN mkdir -p /app/pages

COPY audit.py /app/audit.py
COPY pages/index.html /app/pages/index.html
COPY pages/form.html /app/pages/form.html
COPY pages/content.html /app/pages/content.html
COPY pages/complex.html /app/pages/complex.html
COPY pages/styled.html /app/pages/styled.html
COPY baseline_wcag_map.json /app/baseline_wcag_map.json

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 beautifulsoup4==4.12.3 tinycss2==1.4.0
