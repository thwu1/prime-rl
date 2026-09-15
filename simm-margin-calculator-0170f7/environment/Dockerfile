FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip default-jdk && \
    rm -rf /var/lib/apt/lists/*


COPY src/ /app/src/
COPY data/ /app/data/
COPY portfolios/ /app/portfolios/

RUN cp -r /app/data /app/.data.bak && cp -r /app/portfolios /app/.portfolios.bak && cp -r /app/src /app/.src.bak

WORKDIR /app
