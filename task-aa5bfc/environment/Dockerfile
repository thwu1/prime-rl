FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    default-jdk \
    python3-pip \
    jq \
    make \
    libxml2-utils \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src/main/java/swift /app/messages /app/output /app/build /app/schema

COPY src/main/java/swift/Mt103ValidationEngine.java /app/src/main/java/swift/Mt103ValidationEngine.java
COPY src/main/java/swift/BlockParser.java /app/src/main/java/swift/BlockParser.java
COPY src/main/java/swift/FieldValidator.java /app/src/main/java/swift/FieldValidator.java
COPY src/main/java/swift/CrossFieldValidator.java /app/src/main/java/swift/CrossFieldValidator.java
COPY src/main/java/swift/StpChecker.java /app/src/main/java/swift/StpChecker.java
COPY src/main/java/swift/IbanValidator.java /app/src/main/java/swift/IbanValidator.java
COPY src/main/java/swift/ValidationError.java /app/src/main/java/swift/ValidationError.java
COPY src/main/java/swift/Mt103Message.java /app/src/main/java/swift/Mt103Message.java
COPY src/main/java/swift/Pacs008Mapper.java /app/src/main/java/swift/Pacs008Mapper.java
COPY messages/batch.fin /app/messages/batch.fin
COPY Makefile /app/Makefile
COPY schema/pacs008_subset.xsd /app/schema/pacs008_subset.xsd


WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
