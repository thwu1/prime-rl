FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y default-jdk python3-pip && rm -rf /var/lib/apt/lists/*


COPY src/ /app/src/
COPY config/ /app/config/
COPY compile.sh /app/compile.sh
RUN chmod +x /app/compile.sh

WORKDIR /app
