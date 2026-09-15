FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    default-jdk \
    maven \
    jq \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*


WORKDIR /app
COPY pom.xml /app/pom.xml
COPY pipeline.sh /app/pipeline.sh
COPY data/ /app/data/
COPY src/ /app/src/
RUN chmod +x /app/pipeline.sh
