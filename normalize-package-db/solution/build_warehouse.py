#!/usr/bin/env python3

"""
Build a unified package intelligence warehouse from three data sources:
  - registry.csv (package metadata)
  - downloads.jsonl (CDN download analytics)
  - dependencies.json (dependency graph)
"""

import csv
import json
import os
import re
import sqlite3
import subprocess

from dateutil import parser as dateparser

DB_PATH = "/app/data/warehouse.db"
REGISTRY = "/app/data/registry.csv"
DOWNLOADS = "/app/data/downloads.jsonl"
DEPS_FILE = "/app/data/dependencies.json"


def parse_date(s):
    """Parse various date formats to YYYY-MM-DD."""
    if not s:
        return None
    try:
        dt = dateparser.parse(s, dayfirst=False)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return s


def parse_datetime(s):
    """Parse various datetime formats to YYYY-MM-DDTHH:MM:SS."""
    if not s:
        return None
    try:
        dt = dateparser.parse(s, dayfirst=False)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    except (ValueError, TypeError):
        return s


def parse_author(author_str):
    """Parse 'Name <email>' with whitespace normalization."""
    match = re.match(r"^(.*?)\s*<(.+?)>$", author_str)
    if match:
        name = " ".join(match.group(1).strip().split())
        email = match.group(2).strip()
        return name, email
    return " ".join(author_str.split()), None


def compute_dependency_depths(graph):
    """Compute longest transitive chain depth for every node in the graph."""
    memo = {}

    def depth(pkg):
        if pkg in memo:
            return memo[pkg]
        if pkg not in graph or not graph[pkg]:
            memo[pkg] = 0
            return 0
        max_child = 0
        for dep in graph[pkg]:
            max_child = max(max_child, depth(dep))
        memo[pkg] = max_child + 1
        return memo[pkg]

    for node in graph:
        depth(node)
    return memo


def main():
    # Remove existing database
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    # ---- Read registry ----
    registry_by_name = {}
    with open(REGISTRY, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name_lower = row["name"].lower()
            author_name, author_email = parse_author(row["author"])
            registry_by_name[name_lower] = {
                "version": row["version"],
                "author_name": author_name,
                "author_email": author_email,
                "license": row["license"],
                "category": row["category"],
                "description": row["description"],
                "homepage": row["homepage"],
                "status": row["status"],
                "tags": row["tags"],
                "first_release": row["first_release"],
                "last_update": row["last_update"],
            }

    # ---- Read downloads ----
    downloads_by_name = {}
    with open(DOWNLOADS) as f:
        for line in f:
            rec = json.loads(line.strip())
            name_lower = rec["pkg_name"].lower()
            downloads_by_name[name_lower] = rec

    # ---- Read dependency graph (normalize keys to lowercase) ----
    with open(DEPS_FILE) as f:
        raw_graph = json.load(f)
    dep_graph = {k.lower(): [d.lower() for d in v] for k, v in raw_graph.items()}

    # ---- Compute dependency depths ----
    depth_map = compute_dependency_depths(dep_graph)

    # ---- Build lookup tables ----
    all_names = sorted(set(registry_by_name.keys()) | set(downloads_by_name.keys()))

    authors = {}       # (name, email) -> id
    categories = {}    # category -> id
    licenses = {}      # license -> id

    for name in all_names:
        reg = registry_by_name.get(name)
        if reg:
            akey = (reg["author_name"], reg["author_email"])
            if akey not in authors:
                authors[akey] = len(authors) + 1
            if reg["category"] not in categories:
                categories[reg["category"]] = len(categories) + 1
            if reg["license"] not in licenses:
                licenses[reg["license"]] = len(licenses) + 1

    # ---- Create database ----
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Authors
    cur.execute("CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT, email TEXT)")
    for (aname, aemail), aid in authors.items():
        cur.execute("INSERT INTO authors VALUES (?, ?, ?)", (aid, aname, aemail))

    # Categories
    cur.execute("CREATE TABLE categories (id INTEGER PRIMARY KEY, category TEXT)")
    for cat, cid in categories.items():
        cur.execute("INSERT INTO categories VALUES (?, ?)", (cid, cat))

    # Licenses
    cur.execute("CREATE TABLE licenses (id INTEGER PRIMARY KEY, license TEXT)")
    for lic, lid in licenses.items():
        cur.execute("INSERT INTO licenses VALUES (?, ?)", (lid, lic))

    # Packages
    cur.execute("""CREATE TABLE packages (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        version TEXT,
        description TEXT,
        homepage TEXT,
        status TEXT,
        tags TEXT,
        first_release TEXT,
        last_update TEXT,
        monthly_downloads INTEGER,
        daily_avg INTEGER,
        trend TEXT,
        dependency_depth INTEGER NOT NULL DEFAULT 0,
        author_id INTEGER REFERENCES authors(id),
        category_id INTEGER REFERENCES categories(id),
        license_id INTEGER REFERENCES licenses(id)
    )""")

    pkg_name_to_id = {}
    for pkg_id, name in enumerate(all_names, start=1):
        reg = registry_by_name.get(name)
        dl = downloads_by_name.get(name)

        if reg:
            akey = (reg["author_name"], reg["author_email"])
            author_id = authors[akey]
            category_id = categories[reg["category"]]
            license_id = licenses[reg["license"]]
            version = reg["version"]
            description = reg["description"]
            homepage = reg["homepage"]
            status = reg["status"]
            tags = json.dumps([t.strip() for t in reg["tags"].split(",")])
            first_release = parse_date(reg["first_release"])
            last_update = parse_datetime(reg["last_update"])
        else:
            author_id = None
            category_id = None
            license_id = None
            version = None
            description = None
            homepage = None
            status = None
            tags = None
            first_release = parse_date(dl["first_seen"]) if dl else None
            last_update = None

        if dl:
            monthly_downloads = dl["monthly_downloads"]
            daily_avg = dl["daily_avg"]
            trend = dl["trend"]
            if first_release is None and dl.get("first_seen"):
                first_release = parse_date(dl["first_seen"])
        else:
            monthly_downloads = None
            daily_avg = None
            trend = None

        dep_depth = depth_map.get(name, 0)

        cur.execute(
            "INSERT INTO packages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pkg_id, name, version, description, homepage, status, tags,
             first_release, last_update, monthly_downloads, daily_avg, trend,
             dep_depth, author_id, category_id, license_id),
        )
        pkg_name_to_id[name] = pkg_id

    # Dependencies table
    cur.execute("""CREATE TABLE dependencies (
        package_id INTEGER REFERENCES packages(id),
        dependency_name TEXT NOT NULL,
        PRIMARY KEY (package_id, dependency_name)
    )""")

    for name in all_names:
        deps = dep_graph.get(name, [])
        pid = pkg_name_to_id[name]
        for dep in sorted(deps):
            cur.execute("INSERT INTO dependencies VALUES (?, ?)", (pid, dep))

    conn.commit()
    conn.close()

    # ---- sqlite-utils: FTS5, view, indexes, WAL ----
    subprocess.run(
        ["sqlite-utils", "enable-fts", DB_PATH, "packages", "name", "description",
         "--tokenize", "porter", "--create-triggers"],
        check=True,
    )

    subprocess.run(
        ["sqlite-utils", "create-view", DB_PATH, "package_intelligence",
         """SELECT
                p.id, p.name, p.version,
                a.name as author_name, a.email as author_email,
                c.category, l.license,
                p.monthly_downloads, p.daily_avg, p.trend,
                p.dependency_depth, p.first_release, p.last_update,
                p.description, p.tags, p.status, p.homepage
            FROM packages p
            LEFT JOIN authors a ON p.author_id = a.id
            LEFT JOIN categories c ON p.category_id = c.id
            LEFT JOIN licenses l ON p.license_id = l.id"""],
        check=True,
    )

    subprocess.run(["sqlite-utils", "index-foreign-keys", DB_PATH], check=True)
    subprocess.run(["sqlite-utils", "enable-wal", DB_PATH], check=True)

    print(f"Warehouse built: {DB_PATH}")
    # Verify counts
    conn = sqlite3.connect(DB_PATH)
    for t in ("packages", "authors", "categories", "licenses", "dependencies"):
        c = conn.execute(f"SELECT count(*) FROM [{t}]").fetchone()[0]
        print(f"  {t}: {c} rows")
    conn.close()


if __name__ == "__main__":
    main()
