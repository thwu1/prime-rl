FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y gcc make python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app /opt/ntp_src

COPY Makefile /app/Makefile
COPY ntp_types.h /app/ntp_types.h
COPY ntp_ts.h /app/ntp_ts.h
COPY ntp_ts.c /app/ntp_ts.c
COPY ntp_filter.h /app/ntp_filter.h
COPY ntp_filter.c /app/ntp_filter.c
COPY ntp_select.h /app/ntp_select.h
COPY ntp_select.c /app/ntp_select.c
COPY ntp_pipeline.c /app/ntp_pipeline.c
COPY peers_input.txt /app/peers_input.txt

COPY Makefile /opt/ntp_src/Makefile
COPY ntp_types.h /opt/ntp_src/ntp_types.h
COPY ntp_ts.h /opt/ntp_src/ntp_ts.h
COPY ntp_ts.c /opt/ntp_src/ntp_ts.c
COPY ntp_filter.h /opt/ntp_src/ntp_filter.h
COPY ntp_filter.c /opt/ntp_src/ntp_filter.c
COPY ntp_select.h /opt/ntp_src/ntp_select.h
COPY ntp_select.c /opt/ntp_src/ntp_select.c
COPY ntp_pipeline.c /opt/ntp_src/ntp_pipeline.c
COPY peers_input.txt /opt/ntp_src/peers_input.txt

WORKDIR /app
