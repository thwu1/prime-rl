
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    bash \
    && rm -rf /var/lib/apt/lists/*

# Create repository directory structure
RUN mkdir -p /app/repo/netutils \
             /app/repo/datastore \
             /app/repo/webproxy \
             /app/repo/logcollector \
             /app/repo/loganalyzer \
             /app/repo/appserver \
             /app/results

# Copy PKGBUILDs into the repository
COPY pkgbuilds/netutils /app/repo/netutils/PKGBUILD
COPY pkgbuilds/datastore /app/repo/datastore/PKGBUILD
COPY pkgbuilds/webproxy /app/repo/webproxy/PKGBUILD
COPY pkgbuilds/logcollector /app/repo/logcollector/PKGBUILD
COPY pkgbuilds/loganalyzer /app/repo/loganalyzer/PKGBUILD
COPY pkgbuilds/appserver /app/repo/appserver/PKGBUILD

WORKDIR /app
