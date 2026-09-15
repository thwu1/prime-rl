FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    sqlite3 \
    graphviz \
    jq \
    && rm -rf /var/lib/apt/lists/*

COPY pkgbuilds/ /tmp/pkgbuilds/

RUN mkdir -p /app/ecosystem/baselib \
             /app/ecosystem/baselib-git \
             /app/ecosystem/datastore \
             /app/ecosystem/webapp \
             /app/ecosystem/monitor \
             /app/ecosystem/dashboard \
             /app/ecosystem/toolkit \
             /app/ecosystem/alerter \
             /app/ecosystem/netstack \
             /app/ecosystem/appframework && \
    cp /tmp/pkgbuilds/baselib /app/ecosystem/baselib/PKGBUILD && \
    cp /tmp/pkgbuilds/baselib-git /app/ecosystem/baselib-git/PKGBUILD && \
    cp /tmp/pkgbuilds/datastore /app/ecosystem/datastore/PKGBUILD && \
    cp /tmp/pkgbuilds/webapp /app/ecosystem/webapp/PKGBUILD && \
    cp /tmp/pkgbuilds/monitor /app/ecosystem/monitor/PKGBUILD && \
    cp /tmp/pkgbuilds/dashboard /app/ecosystem/dashboard/PKGBUILD && \
    cp /tmp/pkgbuilds/toolkit /app/ecosystem/toolkit/PKGBUILD && \
    cp /tmp/pkgbuilds/alerter /app/ecosystem/alerter/PKGBUILD && \
    cp /tmp/pkgbuilds/netstack /app/ecosystem/netstack/PKGBUILD && \
    cp /tmp/pkgbuilds/appframework /app/ecosystem/appframework/PKGBUILD && \
    rm -rf /tmp/pkgbuilds

WORKDIR /app
