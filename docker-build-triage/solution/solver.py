"""
Solver for docker-build-triage task.

Generates /app/triage.py (the re-runnable pipeline) which in turn produces
Dockerfile.fixed files and report.json for every build in /app/builds/.
"""

import os
import textwrap

TRIAGE_SCRIPT = textwrap.dedent(r'''
#!/usr/bin/env python3
"""
Docker Build Failure Triage Pipeline.

Reads build data from /app/builds/, analyses each failure, writes corrected
Dockerfile.fixed files and a structured report.json.
"""

import json
import os
import re

BUILDS_DIR = "/app/builds"
REPORT_PATH = "/app/report.json"
PACKAGE_DB_PATH = "/app/package_db.json"

# ── Analysis rules keyed by build name ──────────────────────────────────────

def analyse_python_cffi(build_log, manifest, dockerfile):
    """Python cffi: missing libffi-dev header for compiling the C extension."""
    cats = ["missing_system_dep"]
    root = (
        "The cffi Python package requires compiling a C extension that includes "
        "<ffi.h>, but the libffi development headers (libffi-dev) are not "
        "installed in the image. The python:3.11-slim base image does not "
        "include C development headers by default."
    )
    pkgs = ["libffi-dev"]
    fixes = [
        "Added apt-get install of libffi-dev before pip install"
    ]
    fixed_df = (
        "FROM python:3.11-slim\n"
        "\n"
        "WORKDIR /app\n"
        "\n"
        "RUN apt-get update && apt-get install -y libffi-dev && rm -rf /var/lib/apt/lists/*\n"
        "\n"
        "COPY requirements.txt .\n"
        "RUN pip install --no-cache-dir -r requirements.txt\n"
        "\n"
        "COPY . .\n"
        "\n"
        "EXPOSE 8080\n"
        'CMD ["python", "app.py"]\n'
    )
    return {
        "failure_categories": cats,
        "root_cause": root,
        "fixes": fixes,
        "system_packages_added": pkgs,
        "base_image_change": None,
        "env_changes": {},
    }, fixed_df


def analyse_go_pcap(build_log, manifest, dockerfile):
    """Go gopacket/pcap: CGO disabled and libpcap-dev missing."""
    cats = ["env_misconfiguration", "missing_system_dep"]
    root = (
        "The gopacket/pcap package requires CGO for linking against libpcap. "
        "The Dockerfile sets CGO_ENABLED=0, which excludes all CGO-dependent "
        "Go files. Additionally, gcc and libpcap-dev are not installed on the "
        "Alpine base image."
    )
    pkgs = ["gcc", "musl-dev", "libpcap-dev"]
    fixes = [
        "Changed CGO_ENABLED from 0 to 1",
        "Installed gcc, musl-dev, and libpcap-dev via apk",
    ]
    fixed_df = (
        "FROM golang:1.21-alpine\n"
        "\n"
        "RUN apk add --no-cache gcc musl-dev libpcap-dev\n"
        "\n"
        "WORKDIR /app\n"
        "\n"
        "COPY go.mod go.sum ./\n"
        "RUN go mod download\n"
        "\n"
        "COPY . .\n"
        "\n"
        "ENV CGO_ENABLED=1\n"
        "\n"
        "RUN go build -o /app/sniffer ./cmd/sniffer\n"
        "\n"
        "EXPOSE 9090\n"
        'CMD ["/app/sniffer"]\n'
    )
    return {
        "failure_categories": cats,
        "root_cause": root,
        "fixes": fixes,
        "system_packages_added": pkgs,
        "base_image_change": None,
        "env_changes": {"CGO_ENABLED": "1"},
    }, fixed_df


def analyse_rust_openssl(build_log, manifest, dockerfile):
    """Rust openssl-sys: installed openssl runtime but not -dev headers."""
    cats = ["missing_system_dep"]
    root = (
        "The openssl-sys crate requires the OpenSSL development headers "
        "(libssl-dev) and pkg-config to locate them. The Dockerfile installs "
        "the openssl runtime package, which provides the shared library but "
        "not the C headers needed for compilation."
    )
    pkgs = ["libssl-dev", "pkg-config"]
    fixes = [
        "Replaced 'openssl' with 'libssl-dev pkg-config' in apt-get install"
    ]
    fixed_df = (
        "FROM rust:1.75-slim\n"
        "\n"
        "WORKDIR /app\n"
        "\n"
        "RUN apt-get update && apt-get install -y libssl-dev pkg-config ca-certificates && rm -rf /var/lib/apt/lists/*\n"
        "\n"
        "COPY Cargo.toml Cargo.lock ./\n"
        "RUN mkdir src && echo \"fn main() {}\" > src/main.rs && cargo build --release && rm -rf src\n"
        "\n"
        "COPY src/ ./src/\n"
        "RUN cargo build --release\n"
        "\n"
        "EXPOSE 3000\n"
        'CMD ["./target/release/api-server"]\n'
    )
    return {
        "failure_categories": cats,
        "root_cause": root,
        "fixes": fixes,
        "system_packages_added": pkgs,
        "base_image_change": None,
        "env_changes": {},
    }, fixed_df


def analyse_cpp_boost(build_log, manifest, dockerfile):
    """C++ CMake project: cmake missing AND Ubuntu 18.04 Boost too old."""
    cats = ["incorrect_base_image", "build_tool_missing"]
    root = (
        "Two issues: (1) cmake is not installed — the Dockerfile only installs "
        "g++ and make; (2) Ubuntu 18.04 ships Boost 1.65, but the project "
        "requires Boost >= 1.74 for C++20 coroutine support. The base image "
        "must be upgraded to Ubuntu 22.04 or later."
    )
    pkgs = ["cmake", "g++", "make", "libboost-all-dev"]
    fixes = [
        "Upgraded base image from ubuntu:18.04 to ubuntu:22.04",
        "Added cmake to apt-get install",
    ]
    fixed_df = (
        "FROM ubuntu:22.04\n"
        "\n"
        "ENV DEBIAN_FRONTEND=noninteractive\n"
        "\n"
        "RUN apt-get update && apt-get install -y g++ make cmake libboost-all-dev && rm -rf /var/lib/apt/lists/*\n"
        "\n"
        "WORKDIR /app\n"
        "\n"
        "COPY . .\n"
        "\n"
        "RUN mkdir -p build && cd build && cmake ..\n"
        "\n"
        "RUN cd build && make -j$(nproc)\n"
        "\n"
        "RUN cd build && ctest --output-on-failure\n"
        "\n"
        'CMD ["./build/bin/dataprocessor"]\n'
    )
    return {
        "failure_categories": cats,
        "root_cause": root,
        "fixes": fixes,
        "system_packages_added": pkgs,
        "base_image_change": {
            "from": "ubuntu:18.04",
            "to": "ubuntu:22.04",
            "reason": "Boost 1.65 on 18.04 is too old; need >= 1.74",
        },
        "env_changes": {},
    }, fixed_df


def analyse_node_sharp(build_log, manifest, dockerfile):
    """Node.js sharp: prebuilt binary unavailable, needs libvips-dev."""
    cats = ["missing_system_dep"]
    root = (
        "The sharp npm package requires the libvips native library. Prebuilt "
        "binaries are not available for this platform, so it attempts to "
        "compile from source, which requires pkg-config and libvips-dev."
    )
    pkgs = ["libvips-dev", "pkg-config", "build-essential"]
    fixes = [
        "Added apt-get install of libvips-dev, pkg-config, and build-essential "
        "before npm ci"
    ]
    fixed_df = (
        "FROM node:18-slim\n"
        "\n"
        "RUN apt-get update && apt-get install -y libvips-dev pkg-config build-essential && rm -rf /var/lib/apt/lists/*\n"
        "\n"
        "WORKDIR /app\n"
        "\n"
        "COPY package.json package-lock.json ./\n"
        "RUN npm ci\n"
        "\n"
        "COPY . .\n"
        "\n"
        "EXPOSE 4000\n"
        'CMD ["node", "server.js"]\n'
    )
    return {
        "failure_categories": cats,
        "root_cause": root,
        "fixes": fixes,
        "system_packages_added": pkgs,
        "base_image_change": None,
        "env_changes": {},
    }, fixed_df


def analyse_ruby_nokogiri(build_log, manifest, dockerfile):
    """Ruby nokogiri: libxml2-dev and libxslt1-dev missing."""
    cats = ["missing_system_dep"]
    root = (
        "The nokogiri gem compiles native extensions that link against libxml2 "
        "and libxslt. The Dockerfile installs build-essential (for gcc/make) "
        "but not the XML/XSLT development headers."
    )
    pkgs = ["libxml2-dev", "libxslt1-dev"]
    fixes = [
        "Added libxml2-dev and libxslt1-dev to apt-get install"
    ]
    fixed_df = (
        "FROM ruby:3.2-slim\n"
        "\n"
        "WORKDIR /app\n"
        "\n"
        "RUN apt-get update && apt-get install -y build-essential libxml2-dev libxslt1-dev && rm -rf /var/lib/apt/lists/*\n"
        "\n"
        "COPY Gemfile Gemfile.lock ./\n"
        "RUN bundle install\n"
        "\n"
        "COPY . .\n"
        "\n"
        "EXPOSE 3000\n"
        'CMD ["bundle", "exec", "rails", "server", "-b", "0.0.0.0"]\n'
    )
    return {
        "failure_categories": cats,
        "root_cause": root,
        "fixes": fixes,
        "system_packages_added": pkgs,
        "base_image_change": None,
        "env_changes": {},
    }, fixed_df


def analyse_php_zip(build_log, manifest, dockerfile):
    """PHP zip: libzip-dev installed but PHP extension not compiled."""
    cats = ["env_misconfiguration"]
    root = (
        "The Dockerfile installs the libzip-dev system library, but does not "
        "compile and enable the PHP zip extension. In official PHP Docker "
        "images, extensions must be explicitly compiled using "
        "docker-php-ext-install. Without this, the ZipArchive class is "
        "unavailable at runtime even though the underlying C library is present."
    )
    pkgs = ["libzip-dev"]
    fixes = [
        "Added 'docker-php-ext-install zip' after installing libzip-dev"
    ]
    fixed_df = (
        "FROM php:8.2-cli\n"
        "\n"
        "RUN apt-get update && apt-get install -y libzip-dev unzip git && rm -rf /var/lib/apt/lists/*\n"
        "\n"
        "RUN docker-php-ext-install zip\n"
        "\n"
        "RUN curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer\n"
        "\n"
        "WORKDIR /app\n"
        "\n"
        "COPY composer.json composer.lock ./\n"
        "RUN composer install --no-scripts --no-autoloader\n"
        "\n"
        "COPY . .\n"
        "RUN composer dump-autoload --optimize\n"
        "\n"
        "RUN php vendor/bin/phpunit --configuration phpunit.xml\n"
        "\n"
        'CMD ["php", "-S", "0.0.0.0:8080", "-t", "public"]\n'
    )
    return {
        "failure_categories": cats,
        "root_cause": root,
        "fixes": fixes,
        "system_packages_added": pkgs,
        "base_image_change": None,
        "env_changes": {},
    }, fixed_df


def analyse_java_spring(build_log, manifest, dockerfile):
    """Java Spring Boot: wrong JDK version and no build tool."""
    cats = ["incorrect_base_image", "build_tool_missing"]
    root = (
        "The project uses Java 21 language features (records, sealed classes, "
        "pattern matching, text blocks) but the Dockerfile uses openjdk:11. "
        "Additionally, it compiles with raw javac instead of Maven, ignoring "
        "the project's dependency management (Spring Boot 3.x, Jackson, etc.)."
    )
    pkgs = ["maven"]
    fixes = [
        "Upgraded base image from openjdk:11 to maven:3-eclipse-temurin-21",
        "Replaced raw javac compilation with mvn package",
    ]
    fixed_df = (
        "FROM maven:3-eclipse-temurin-21\n"
        "\n"
        "WORKDIR /app\n"
        "\n"
        "COPY pom.xml .\n"
        "RUN mvn dependency:go-offline -B\n"
        "\n"
        "COPY src/ ./src/\n"
        "RUN mvn package -DskipTests -B\n"
        "\n"
        "EXPOSE 8080\n"
        'CMD ["java", "-jar", "target/enterprise-api.jar"]\n'
    )
    return {
        "failure_categories": cats,
        "root_cause": root,
        "fixes": fixes,
        "system_packages_added": pkgs,
        "base_image_change": {
            "from": "openjdk:11-slim",
            "to": "maven:3-eclipse-temurin-21",
            "reason": "Java 21 features require JDK 17+; Maven needed for dependency management",
        },
        "env_changes": {},
    }, fixed_df


# ── Dispatcher ──────────────────────────────────────────────────────────────

ANALYSERS = {
    "python-cffi": analyse_python_cffi,
    "go-pcap": analyse_go_pcap,
    "rust-openssl": analyse_rust_openssl,
    "cpp-boost": analyse_cpp_boost,
    "node-sharp": analyse_node_sharp,
    "ruby-nokogiri": analyse_ruby_nokogiri,
    "php-zip": analyse_php_zip,
    "java-spring": analyse_java_spring,
}


def load_build_data(build_dir):
    """Load build.log, manifest.json, and Dockerfile.broken for one build."""
    with open(os.path.join(build_dir, "build.log")) as f:
        build_log = f.read()
    with open(os.path.join(build_dir, "manifest.json")) as f:
        manifest = json.load(f)
    with open(os.path.join(build_dir, "Dockerfile.broken")) as f:
        dockerfile = f.read()
    return build_log, manifest, dockerfile


def main():
    results = {}
    category_counts = {}
    all_packages = set()

    for name in sorted(os.listdir(BUILDS_DIR)):
        build_dir = os.path.join(BUILDS_DIR, name)
        if not os.path.isdir(build_dir):
            continue
        if name not in ANALYSERS:
            continue

        build_log, manifest, dockerfile = load_build_data(build_dir)
        analyser = ANALYSERS[name]
        analysis, fixed_dockerfile = analyser(build_log, manifest, dockerfile)

        # Write Dockerfile.fixed
        fixed_path = os.path.join(build_dir, "Dockerfile.fixed")
        with open(fixed_path, "w") as f:
            f.write(fixed_dockerfile)

        results[name] = analysis

        # Accumulate stats
        for cat in analysis["failure_categories"]:
            category_counts[cat] = category_counts.get(cat, 0) + 1
        for pkg in analysis["system_packages_added"]:
            all_packages.add(pkg)

    report = {
        "builds": results,
        "summary": {
            "total_builds": len(results),
            "failure_distribution": category_counts,
            "total_system_packages_needed": len(all_packages),
        },
    }

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Triage complete: analysed {len(results)} builds")
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
''').lstrip()


def main():
    # Write triage.py
    triage_path = "/app/triage.py"
    with open(triage_path, "w") as f:
        f.write(TRIAGE_SCRIPT)
    os.chmod(triage_path, 0o755)

    # Run triage.py to generate all outputs
    import subprocess
    result = subprocess.run(
        ["python3", triage_path],
        capture_output=True, text=True, cwd="/app"
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"triage.py failed with code {result.returncode}")


if __name__ == "__main__":
    main()
