FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y gcc make strace gdb python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /app/bin /app/etc /app/logs /app/scripts /app/run /app/analysis

COPY src/supervisor.c /app/src/supervisor.c
COPY scripts/cleanup.sh /app/scripts/cleanup.sh
COPY Makefile /app/Makefile
COPY etc/workers.conf /app/etc/workers.conf
COPY etc/supervisor.conf /app/etc/supervisor.conf
COPY logs/incident_report.txt /app/logs/incident_report.txt
COPY logs/postmortem_notes.txt /app/logs/postmortem_notes.txt
COPY logs/syslog_excerpt.txt /app/logs/syslog_excerpt.txt
COPY logs/strace_excerpt.log /app/logs/strace_excerpt.log

RUN chmod +x /app/scripts/cleanup.sh

WORKDIR /app
