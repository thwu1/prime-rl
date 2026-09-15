
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        jq \
        curl \
        unzip \
        libxml2-utils \
        xmlstarlet \
        default-jre-headless \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/oscal-cli && \
    cd /opt/oscal-cli && \
    curl -sL https://repo1.maven.org/maven2/gov/nist/secauto/oscal/tools/oscal-cli/cli-core/1.0.3/cli-core-1.0.3-oscal-cli.zip -o /tmp/oscal-cli.zip && \
    unzip -q /tmp/oscal-cli.zip && \
    rm /tmp/oscal-cli.zip && \
    chmod +x bin/oscal-cli
ENV PATH="/opt/oscal-cli/bin:${PATH}"

RUN mkdir -p /app /tests /solution /logs/verifier

COPY catalog.json /app/catalog.json
COPY baseline_profile.json /app/baseline_profile.json
COPY org_profile.json /app/org_profile.json
COPY system_ssp.json /app/system_ssp.json
COPY poam.xml /app/poam.xml

WORKDIR /app
