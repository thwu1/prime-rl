FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip libxml2-utils jq xmlstarlet xsltproc && \
    rm -rf /var/lib/apt/lists/*


COPY profile/ /app/profile/
COPY profile_ack/ /app/profile_ack/
COPY messages/ /app/messages/
COPY messages_ack/ /app/messages_ack/
COPY schematron/ /app/schematron/

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
