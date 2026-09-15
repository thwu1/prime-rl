FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    default-jdk \
    maven \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src/main/java/conjanalysis /app/data /app/target

COPY pom.xml /app/pom.xml
COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh
COPY src/main/java/conjanalysis/Main.java /app/src/main/java/conjanalysis/Main.java
COPY src/main/java/conjanalysis/CdmParser.java /app/src/main/java/conjanalysis/CdmParser.java
COPY src/main/java/conjanalysis/CdmData.java /app/src/main/java/conjanalysis/CdmData.java
COPY src/main/java/conjanalysis/CollisionAnalyzer.java /app/src/main/java/conjanalysis/CollisionAnalyzer.java
COPY data/CDMExample1.txt /app/data/CDMExample1.txt
COPY data/encounter_leo.txt /app/data/encounter_leo.txt


WORKDIR /app
