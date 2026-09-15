FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip xmlstarlet jq sqlite3 graphviz && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/configs

COPY configs/ /app/configs/
COPY ted_database.xml /app/ted_database.xml
COPY lsp_order.txt /app/lsp_order.txt
COPY nms_setup.sql /tmp/nms_setup.sql
RUN sqlite3 /app/nms.db < /tmp/nms_setup.sql && rm /tmp/nms_setup.sql

WORKDIR /app
