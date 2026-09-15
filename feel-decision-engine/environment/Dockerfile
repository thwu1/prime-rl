FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y default-jdk python3-pip && rm -rf /var/lib/apt/lists/*


WORKDIR /app

COPY src/ src/
COPY build.sh run.sh ./
RUN chmod +x build.sh run.sh
