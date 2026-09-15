
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    openjdk-17-jdk-headless \
    maven \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

RUN mkdir -p /app/src/main/java/com/example/demo /app/src/main/resources

COPY pom.xml /app/pom.xml
COPY DemoApplication.java /app/src/main/java/com/example/demo/DemoApplication.java
COPY UserController.java /app/src/main/java/com/example/demo/UserController.java
COPY UserService.java /app/src/main/java/com/example/demo/UserService.java
COPY MetricsFilter.java /app/src/main/java/com/example/demo/MetricsFilter.java
COPY SecurityConfig.java /app/src/main/java/com/example/demo/SecurityConfig.java
COPY WebConfig.java /app/src/main/java/com/example/demo/WebConfig.java
COPY CacheConfig.java /app/src/main/java/com/example/demo/CacheConfig.java
COPY DataExporter.java /app/src/main/java/com/example/demo/DataExporter.java
COPY application.properties /app/src/main/resources/application.properties
COPY filter-config.properties /app/src/main/resources/filter-config.properties

# Pre-cache Spring Boot 3.0 + Security dependencies (compile will fail due to
# unmigrated imports and removed APIs, but dependency:resolve just downloads JARs)
RUN cd /app && mvn dependency:resolve -q 2>/dev/null; exit 0

WORKDIR /app
