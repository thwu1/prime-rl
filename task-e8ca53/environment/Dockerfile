FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip git xmlstarlet jq && \
    rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/vintages/116-344 /app/vintages/117-81 /app/vintages/117-262 /app/vintages/118-82 /app/output

COPY vintages/116-344/title-09.xml /app/vintages/116-344/title-09.xml
COPY vintages/117-81/title-09.xml /app/vintages/117-81/title-09.xml
COPY vintages/117-262/title-09.xml /app/vintages/117-262/title-09.xml
COPY vintages/118-82/title-09.xml /app/vintages/118-82/title-09.xml
COPY manifest.json /app/manifest.json
COPY title_headings.json /app/title_headings.json
COPY SPEC.md /app/SPEC.md

WORKDIR /app
