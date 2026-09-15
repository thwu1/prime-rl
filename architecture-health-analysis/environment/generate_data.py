#!/usr/bin/env python3
"""Generate architecture data for the BigSpender drift forensics task.

Creates divergent views of the architecture:
1. intended.dot -- Graphviz DOT of the intended architecture (with chains, legend, traps)
2. source_deps/*.imports -- Static code-level dependencies
3. traces/gateway.jsonl.gz -- Gzipped JSONL runtime traces from API gateway
4. traces/monitoring.csv.gz -- Gzipped CSV runtime traces from monitoring system
5. governance.db -- SQLite database with component metadata and governance rules
"""
import json
import gzip
import csv
import io
import os
import random
import sqlite3

COMPONENTS = {
    "persistence-api": {"abstract_types": 12, "concrete_types": 2, "layer": "infrastructure-api", "business_criticality": 5},
    "messaging-api": {"abstract_types": 8, "concrete_types": 1, "layer": "infrastructure-api", "business_criticality": 4},
    "security-api": {"abstract_types": 10, "concrete_types": 2, "layer": "infrastructure-api", "business_criticality": 5},
    "caching-api": {"abstract_types": 6, "concrete_types": 1, "layer": "infrastructure-api", "business_criticality": 3},
    "logging-api": {"abstract_types": 5, "concrete_types": 1, "layer": "infrastructure-api", "business_criticality": 2},
    "user-domain": {"abstract_types": 4, "concrete_types": 8, "layer": "domain", "business_criticality": 4},
    "product-domain": {"abstract_types": 5, "concrete_types": 10, "layer": "domain", "business_criticality": 5},
    "order-domain": {"abstract_types": 6, "concrete_types": 12, "layer": "domain", "business_criticality": 5},
    "payment-domain": {"abstract_types": 4, "concrete_types": 9, "layer": "domain", "business_criticality": 5},
    "inventory-domain": {"abstract_types": 3, "concrete_types": 7, "layer": "domain", "business_criticality": 4},
    "catalog-domain": {"abstract_types": 3, "concrete_types": 8, "layer": "domain", "business_criticality": 3},
    "pricing-domain": {"abstract_types": 2, "concrete_types": 6, "layer": "domain", "business_criticality": 4},
    "shipping-domain": {"abstract_types": 3, "concrete_types": 7, "layer": "domain", "business_criticality": 4},
    "notification-domain": {"abstract_types": 2, "concrete_types": 5, "layer": "domain", "business_criticality": 2},
    "auth-service": {"abstract_types": 1, "concrete_types": 8, "layer": "application", "business_criticality": 5},
    "product-service": {"abstract_types": 2, "concrete_types": 11, "layer": "application", "business_criticality": 4},
    "order-service": {"abstract_types": 2, "concrete_types": 14, "layer": "application", "business_criticality": 5},
    "payment-service": {"abstract_types": 1, "concrete_types": 10, "layer": "application", "business_criticality": 5},
    "cart-service": {"abstract_types": 1, "concrete_types": 9, "layer": "application", "business_criticality": 4},
    "search-service": {"abstract_types": 1, "concrete_types": 7, "layer": "application", "business_criticality": 3},
    "recommendation-service": {"abstract_types": 0, "concrete_types": 8, "layer": "application", "business_criticality": 2},
    "analytics-service": {"abstract_types": 1, "concrete_types": 6, "layer": "application", "business_criticality": 2},
    "reporting-service": {"abstract_types": 0, "concrete_types": 9, "layer": "application", "business_criticality": 2},
    "postgres-adapter": {"abstract_types": 0, "concrete_types": 6, "layer": "infrastructure-adapter", "business_criticality": 4},
    "redis-adapter": {"abstract_types": 0, "concrete_types": 4, "layer": "infrastructure-adapter", "business_criticality": 3},
    "rabbitmq-adapter": {"abstract_types": 0, "concrete_types": 5, "layer": "infrastructure-adapter", "business_criticality": 3},
    "elasticsearch-adapter": {"abstract_types": 0, "concrete_types": 4, "layer": "infrastructure-adapter", "business_criticality": 2},
    "stripe-adapter": {"abstract_types": 0, "concrete_types": 5, "layer": "infrastructure-adapter", "business_criticality": 5},
    "web-frontend": {"abstract_types": 0, "concrete_types": 15, "layer": "presentation", "business_criticality": 4},
    "api-gateway": {"abstract_types": 1, "concrete_types": 12, "layer": "presentation", "business_criticality": 5},
}

# Edges present in ALL three views (intended + static + runtime)
CONFORMANT = [
    ["web-frontend", "api-gateway"],
    ["web-frontend", "auth-service"],
    ["api-gateway", "auth-service"],
    ["api-gateway", "product-service"],
    ["api-gateway", "order-service"],
    ["api-gateway", "payment-service"],
    ["api-gateway", "cart-service"],
    ["api-gateway", "search-service"],
    ["auth-service", "user-domain"],
    ["auth-service", "security-api"],
    ["product-service", "product-domain"],
    ["product-service", "catalog-domain"],
    ["product-service", "pricing-domain"],
    ["order-service", "order-domain"],
    ["order-service", "payment-domain"],
    ["order-service", "inventory-domain"],
    ["order-service", "shipping-domain"],
    ["payment-service", "payment-domain"],
    ["cart-service", "product-domain"],
    ["cart-service", "pricing-domain"],
    ["cart-service", "order-service"],
    ["search-service", "product-domain"],
    ["search-service", "catalog-domain"],
    ["recommendation-service", "product-domain"],
    ["recommendation-service", "analytics-service"],
    ["analytics-service", "order-domain"],
    ["analytics-service", "user-domain"],
    ["reporting-service", "order-domain"],
    ["reporting-service", "analytics-service"],
    ["reporting-service", "product-domain"],
    ["user-domain", "persistence-api"],
    ["user-domain", "security-api"],
    ["product-domain", "persistence-api"],
    ["product-domain", "caching-api"],
    ["order-domain", "persistence-api"],
    ["order-domain", "messaging-api"],
    ["payment-domain", "persistence-api"],
    ["payment-domain", "security-api"],
    ["payment-domain", "messaging-api"],
    ["inventory-domain", "persistence-api"],
    ["inventory-domain", "messaging-api"],
    ["catalog-domain", "persistence-api"],
    ["catalog-domain", "caching-api"],
    ["pricing-domain", "persistence-api"],
    ["pricing-domain", "caching-api"],
    ["shipping-domain", "persistence-api"],
    ["shipping-domain", "messaging-api"],
    ["notification-domain", "messaging-api"],
    ["notification-domain", "logging-api"],
    ["postgres-adapter", "persistence-api"],
    ["redis-adapter", "caching-api"],
    ["rabbitmq-adapter", "messaging-api"],
]

# In intended spec only -- planned but never implemented
UNIMPLEMENTED = [
    ["elasticsearch-adapter", "persistence-api"],
    ["stripe-adapter", "security-api"],
    ["notification-domain", "user-domain"],
]

# In intended + static code, but never observed at runtime
DEAD_CODE = [
    ["catalog-domain", "pricing-domain"],
    ["pricing-domain", "catalog-domain"],
    ["order-domain", "payment-domain"],
    ["payment-domain", "order-domain"],
]

# In static code only -- coded but not in spec, never called at runtime
UNDOCUMENTED_STATIC = [
    ["analytics-service", "recommendation-service"],
    ["search-service", "elasticsearch-adapter"],
]

# In runtime only -- no code import, not in spec (dynamic/reflection)
SHADOW_RUNTIME = [
    ["security-api", "web-frontend"],
    ["notification-domain", "recommendation-service"],
    ["web-frontend", "reporting-service"],
]

# In static + runtime but not in intended spec -- organic drift
ORGANIC_GROWTH = [
    ["stripe-adapter", "payment-domain"],
    ["elasticsearch-adapter", "caching-api"],
    ["api-gateway", "analytics-service"],
    ["cart-service", "inventory-domain"],
    ["reporting-service", "user-domain"],
]

# Edge chains for DOT file: some intended edges are encoded as A -> B -> C
DOT_CHAINS = [
    ["web-frontend", "api-gateway", "auth-service"],
    ["product-service", "product-domain", "persistence-api"],
    ["recommendation-service", "analytics-service", "order-domain"],
]

REMEDIATION_BUDGET = 12


def _chain_edge_set():
    s = set()
    for chain in DOT_CHAINS:
        for i in range(len(chain) - 1):
            s.add((chain[i], chain[i + 1]))
    return s


def generate_dot(intended_edges):
    chain_edges = _chain_edge_set()

    layers = {
        "presentation": [],
        "application": [],
        "domain": [],
        "infrastructure-api": [],
        "infrastructure-adapter": [],
    }
    for name, meta in COMPONENTS.items():
        layers[meta["layer"]].append(name)

    layer_labels = {
        "presentation": "Presentation",
        "application": "Application Services",
        "domain": "Domain",
        "infrastructure-api": "Infrastructure API",
        "infrastructure-adapter": "Infrastructure Adapters",
    }
    layer_colors = {
        "presentation": ("#FFEBEE", "#FFCDD2"),
        "application": ("#FFF3E0", "#FFE0B2"),
        "domain": ("#E8F5E9", "#C8E6C9"),
        "infrastructure-api": ("#E8F0FE", "#BBDEFB"),
        "infrastructure-adapter": ("#F3E5F5", "#E1BEE7"),
    }
    edge_styles = {
        "presentation": ' [color="#1565C0", style=bold]',
        "application": "",
        "domain": " [style=dashed]",
        "infrastructure-adapter": " [style=dotted]",
    }

    lines = []
    lines.append("/* BigSpender E-Commerce Platform")
    lines.append(" * Intended Architecture Specification")
    lines.append(" * Derived from Architecture Decision Records (ADR-001 through ADR-047)")
    lines.append(" * Last reviewed: 2024-Q3 Architecture Board")
    lines.append(" *")
    lines.append(' * Proposed: "api-gateway" -> "analytics-service" direct path (ADR-051, under review)')
    lines.append(' * Deprecated: "stripe-adapter" -> "payment-domain" hotfix path (HF-2847, to be removed)')
    lines.append(" */")
    lines.append("digraph BigSpender {")
    lines.append('    graph [rankdir=TB, fontname="Helvetica", compound=true,')
    lines.append('           label="BigSpender - Target Architecture\\n(Approved 2024-08-15)",')
    lines.append("           labelloc=t, fontsize=14];")
    lines.append('    node [shape=component, style=filled, fontname="Helvetica", fontsize=10];')
    lines.append('    edge [fontsize=8, color="#424242"];')
    lines.append("")

    # Layer subgraphs
    for layer_id in ["presentation", "application", "domain", "infrastructure-api", "infrastructure-adapter"]:
        comps = layers[layer_id]
        bg, fg = layer_colors[layer_id]
        cluster_name = "cluster_" + layer_id.replace("-", "_")
        lines.append(f"    /* {layer_labels[layer_id]} Layer */")
        lines.append(f"    subgraph {cluster_name} {{")
        lines.append(f'        label="{layer_labels[layer_id]}";')
        lines.append(f'        style="filled,rounded";')
        lines.append(f'        color="{bg}";')
        for c in sorted(comps):
            lines.append(f'        "{c}" [fillcolor="{fg}"];')
        lines.append("    }")
        lines.append("")

    lines.append("    /* === Dependency Specifications === */")
    lines.append("")

    # Group individual edges by source layer
    layer_order = ["presentation", "application", "domain", "infrastructure-adapter"]
    group_labels = {
        "presentation": "Presentation -> Application Services",
        "application": "Application Services -> Domain / Infrastructure",
        "domain": "Domain -> Infrastructure API",
        "infrastructure-adapter": "Infrastructure Adapters -> Infrastructure API",
    }

    edge_groups = {k: [] for k in layer_order}
    for src, tgt in intended_edges:
        if (src, tgt) in chain_edges:
            continue
        src_layer = COMPONENTS[src]["layer"]
        if src_layer in edge_groups:
            edge_groups[src_layer].append((src, tgt))

    for layer_id in layer_order:
        edges = edge_groups[layer_id]
        layer_chains = [c for c in DOT_CHAINS if COMPONENTS[c[0]]["layer"] == layer_id]
        if not edges and not layer_chains:
            continue

        label = group_labels[layer_id]
        style = edge_styles.get(layer_id, "")
        lines.append(f"    // {label}")

        # Chains first
        for chain in layer_chains:
            chain_str = " -> ".join(f'"{n}"' for n in chain)
            lines.append(f"    {chain_str}{style};")

        # Individual edges
        for src, tgt in edges:
            lines.append(f'    "{src}" -> "{tgt}"{style};')
        lines.append("")

    # Misleading line comment referencing real edge NOT in intended graph
    lines.append('    // NOTE: "notification-domain" -> "recommendation-service" observed at runtime but not specified here')
    lines.append("")

    # Legend subgraph with fake edges
    lines.append("    /* Visual Legend (not part of architecture specification) */")
    lines.append("    subgraph cluster_legend {")
    lines.append('        label="Legend";')
    lines.append('        style="filled,rounded";')
    lines.append('        color="#F5F5F5";')
    lines.append('        node [shape=plaintext, fontsize=8, width=0.3, height=0.2];')
    lines.append('        "legend_specified" [label="Specified"];')
    lines.append('        "legend_dependency" [label="Dependency"];')
    lines.append('        "legend_specified" -> "legend_dependency" [label="intended dep", style=solid, fontsize=7];')
    lines.append('        "legend_violation_src" [label="Component"];')
    lines.append('        "legend_violation_tgt" [label="Target"];')
    lines.append('        "legend_violation_src" -> "legend_violation_tgt" [label="violation", style=dashed, color=red, fontsize=7];')
    lines.append("    }")

    lines.append("}")

    with open("/app/architecture/intended.dot", "w") as f:
        f.write("\n".join(lines) + "\n")


def generate_imports(static_edges):
    deps = {name: [] for name in COMPONENTS}
    for src, tgt in static_edges:
        deps[src].append(tgt)

    for name in sorted(COMPONENTS.keys()):
        path = f"/app/architecture/source_deps/{name}.imports"
        with open(path, "w") as f:
            f.write(f"# Static dependencies for {name}\n")
            f.write("# Auto-extracted from source analysis\n")
            for dep in sorted(deps[name]):
                f.write(dep + "\n")


def generate_traces(gateway_edges, monitoring_edges):
    # Gateway: gzipped JSONL with caller/callee fields
    random.seed(42)
    records = []
    for src, tgt in gateway_edges:
        count = random.randint(15, 120)
        for _ in range(count):
            trace_id = "%032x" % random.getrandbits(128)
            span_id = "%016x" % random.getrandbits(64)
            day = random.randint(1, 28)
            hour = random.randint(0, 23)
            minute = random.randint(0, 59)
            second = random.randint(0, 59)
            ms = random.randint(0, 999)
            timestamp = f"2024-11-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}.{ms:03d}Z"
            latency = random.randint(1, 500)
            status = random.choice(["OK"] * 19 + ["ERROR"])
            records.append({
                "trace_id": trace_id,
                "span_id": span_id,
                "caller": src,
                "callee": tgt,
                "timestamp": timestamp,
                "latency_ms": latency,
                "status": status,
            })
    random.shuffle(records)
    with gzip.open("/app/architecture/traces/gateway.jsonl.gz", "wt") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")

    # Monitoring: gzipped CSV with source/destination columns
    random.seed(99)
    rows = []
    for src, tgt in monitoring_edges:
        count = random.randint(10, 80)
        for _ in range(count):
            day = random.randint(1, 28)
            hour = random.randint(0, 23)
            minute = random.randint(0, 59)
            second = random.randint(0, 59)
            us = random.randint(0, 999999)
            timestamp = f"2024-11-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}.{us:06d}Z"
            duration = random.randint(100, 50000)
            status_code = random.choice([200] * 18 + [500, 503])
            request_id = "%016x" % random.getrandbits(64)
            rows.append([timestamp, src, tgt, str(duration), str(status_code), request_id])
    random.shuffle(rows)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["timestamp", "source", "destination", "duration_us", "status_code", "request_id"])
    writer.writerows(rows)

    with gzip.open("/app/architecture/traces/monitoring.csv.gz", "wt") as f:
        f.write(buf.getvalue())


def generate_governance_db():
    db_path = "/app/architecture/governance.db"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Audit metadata (noise table the agent must navigate around)
    c.execute("""CREATE TABLE audit_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""")
    metadata = [
        ("audit_version", "3.2"),
        ("last_reviewed", "2024-Q3"),
        ("framework", "iSAQB Architecture Conformance Analysis"),
        ("system_name", "BigSpender E-Commerce Platform"),
    ]
    c.executemany("INSERT INTO audit_metadata VALUES (?, ?)", metadata)

    # Components
    c.execute("""CREATE TABLE components (
        name TEXT PRIMARY KEY,
        layer TEXT NOT NULL,
        abstract_types INTEGER NOT NULL,
        concrete_types INTEGER NOT NULL,
        business_criticality INTEGER NOT NULL CHECK(business_criticality BETWEEN 1 AND 5)
    )""")
    for name, meta in sorted(COMPONENTS.items()):
        c.execute(
            "INSERT INTO components VALUES (?, ?, ?, ?, ?)",
            (name, meta["layer"], meta["abstract_types"],
             meta["concrete_types"], meta["business_criticality"]),
        )

    # Layer hierarchy (reference table)
    c.execute("""CREATE TABLE layer_hierarchy (
        layer TEXT PRIMARY KEY,
        level INTEGER NOT NULL,
        description TEXT NOT NULL
    )""")
    hierarchy = [
        ("presentation", 1, "UI and API gateway layer"),
        ("application", 2, "Application services coordinating domain logic"),
        ("domain", 3, "Domain entities and business rules"),
        ("infrastructure-api", 4, "Abstract infrastructure interfaces"),
        ("infrastructure-adapter", 5, "Concrete infrastructure implementations"),
    ]
    c.executemany("INSERT INTO layer_hierarchy VALUES (?, ?, ?)", hierarchy)

    # Classification rules: maps (in_intended, in_static, in_runtime) -> classification
    c.execute("""CREATE TABLE classification_rules (
        in_intended INTEGER NOT NULL CHECK(in_intended IN (0,1)),
        in_static INTEGER NOT NULL CHECK(in_static IN (0,1)),
        in_runtime INTEGER NOT NULL CHECK(in_runtime IN (0,1)),
        classification TEXT NOT NULL UNIQUE,
        PRIMARY KEY (in_intended, in_static, in_runtime)
    )""")
    rules = [
        (1, 1, 1, "conformant"),
        (1, 1, 0, "dead_code"),
        (1, 0, 1, "runtime_drift"),
        (1, 0, 0, "unimplemented"),
        (0, 1, 1, "organic_growth"),
        (0, 1, 0, "undocumented_static"),
        (0, 0, 1, "shadow_runtime"),
    ]
    c.executemany("INSERT INTO classification_rules VALUES (?, ?, ?, ?)", rules)

    # Violation configuration
    c.execute("""CREATE TABLE violation_config (
        classification TEXT PRIMARY KEY,
        erosion_weight REAL NOT NULL,
        primary_action TEXT NOT NULL,
        primary_action_cost INTEGER NOT NULL
    )""")
    violations = [
        ("undocumented_static", 2.0, "remove", 2),
        ("shadow_runtime", 3.0, "block", 4),
        ("organic_growth", 2.0, "remove", 3),
    ]
    c.executemany("INSERT INTO violation_config VALUES (?, ?, ?, ?)", violations)

    # Metric definitions
    c.execute("""CREATE TABLE metric_definitions (
        metric_key TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        description TEXT NOT NULL,
        computation TEXT NOT NULL
    )""")
    metrics = [
        ("Ca", "Afferent Coupling",
         "Number of external components that depend on this component",
         "Count incoming edges in the static dependency graph"),
        ("Ce", "Efferent Coupling",
         "Number of external components this component depends on",
         "Count outgoing edges in the static dependency graph"),
        ("I", "Instability",
         "Ratio indicating component changeability",
         "Ce / (Ca + Ce); defined as 0.0 when Ca + Ce = 0"),
        ("A", "Abstractness",
         "Ratio of abstract types to total types",
         "abstract_types / (abstract_types + concrete_types); defined as 0.0 when total = 0"),
        ("D", "Distance from Main Sequence",
         "Perpendicular normalized distance from the ideal line A + I = 1",
         "|A + I - 1|"),
    ]
    c.executemany("INSERT INTO metric_definitions VALUES (?, ?, ?, ?)", metrics)

    # Global configuration
    c.execute("""CREATE TABLE config (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        description TEXT
    )""")
    config = [
        ("remediation_budget", "12",
         "Maximum total cost units available for remediation actions"),
        ("erosion_formula", "erosion_weight * max(business_criticality_source, business_criticality_target)",
         "Per-edge erosion contribution formula"),
        ("erosion_attribution", "both_endpoints",
         "Erosion score is added to both source and target components"),
        ("alternate_action", "document",
         "Alternative remediation action available for all violation types"),
        ("alternate_action_cost", "1",
         "Cost of the alternate (document) action"),
        ("alternate_reduction_factor", "0.5",
         "Fraction of full erosion reduction achieved by alternate action"),
        ("max_actions_per_edge", "1",
         "Maximum number of remediation actions selectable per violation edge"),
    ]
    c.executemany("INSERT INTO config VALUES (?, ?, ?)", config)

    conn.commit()
    conn.close()


def main():
    os.makedirs("/app/architecture/source_deps", exist_ok=True)
    os.makedirs("/app/architecture/traces", exist_ok=True)
    os.makedirs("/app/results", exist_ok=True)

    intended_edges = CONFORMANT + UNIMPLEMENTED + DEAD_CODE
    static_edges = CONFORMANT + DEAD_CODE + UNDOCUMENTED_STATIC + ORGANIC_GROWTH

    # Split runtime edges between two monitoring systems with overlap
    # Gateway sees service calls + organic growth edges
    gateway_edges = CONFORMANT + ORGANIC_GROWTH
    # Monitoring sees first 30 service calls + shadow (reflection) calls
    monitoring_edges = CONFORMANT[:30] + SHADOW_RUNTIME

    generate_dot(intended_edges)
    generate_imports(static_edges)
    generate_traces(gateway_edges, monitoring_edges)
    generate_governance_db()

    all_runtime = set(tuple(e) for e in gateway_edges + monitoring_edges)
    print("Generated architecture data:")
    print(f"  Intended edges (DOT): {len(intended_edges)}")
    print(f"  Static edges (.imports): {len(static_edges)}")
    print(f"  Runtime edges (gateway+monitoring): {len(all_runtime)}")
    print(f"  Components: {len(COMPONENTS)}")
    print(f"  Governance DB: /app/architecture/governance.db")


if __name__ == "__main__":
    main()
