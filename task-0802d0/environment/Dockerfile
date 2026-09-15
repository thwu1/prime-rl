FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip python3-dev gcc g++ && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install pySDC==5.5.2 -q

RUN mkdir -p /app/docs
COPY project_brief.txt /app/docs/project_brief.txt
WORKDIR /app
