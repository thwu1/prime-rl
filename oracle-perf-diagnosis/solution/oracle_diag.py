#!/usr/bin/env python3
"""
Oracle 19c Performance Diagnostic Peer Review Engine.

Loads raw V$ view data into SQLite, computes correct metrics,
generates gnuplot advisory charts, evaluates two competing DBA reports.

"""

import csv
import json
import os
import sqlite3
import subprocess


def load_csv_to_sqlite(db_path, data_dir):
    """Load all CSV data files into a SQLite database."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    file_schemas = {
        "sysstat_begin": ("sysstat_begin.csv", [
            ("statistic_name", "TEXT"), ("value", "REAL"),
        ]),
        "sysstat_end": ("sysstat_end.csv", [
            ("statistic_name", "TEXT"), ("value", "REAL"),
        ]),
        "time_model": ("time_model.csv", [
            ("stat_name", "TEXT"), ("value_microseconds", "REAL"),
        ]),
        "system_events": ("system_events.csv", [
            ("event", "TEXT"), ("total_waits", "REAL"),
            ("time_waited_micro", "REAL"), ("avg_wait_micro", "REAL"),
        ]),
        "db_cache_advice": ("db_cache_advice.csv", [
            ("name", "TEXT"), ("block_size", "INTEGER"), ("size_factor", "REAL"),
            ("size_for_estimate_mb", "REAL"), ("buffers_for_estimate", "INTEGER"),
            ("estd_physical_read_factor", "REAL"), ("estd_physical_reads", "REAL"),
            ("advice_status", "TEXT"),
        ]),
        "pga_target_advice": ("pga_target_advice.csv", [
            ("pga_target_for_estimate_mb", "REAL"), ("pga_target_factor", "REAL"),
            ("advice_status", "TEXT"), ("estd_extra_bytes_rw", "REAL"),
            ("estd_pga_cache_hit_percentage", "REAL"), ("estd_overalloc_count", "REAL"),
        ]),
        "sql_stats": ("sql_stats.csv", [
            ("sql_id", "TEXT"), ("executions", "REAL"), ("buffer_gets", "REAL"),
            ("disk_reads", "REAL"), ("elapsed_time_us", "REAL"),
            ("cpu_time_us", "REAL"), ("rows_processed", "REAL"),
            ("parse_calls", "REAL"), ("version_count", "REAL"), ("sql_text", "TEXT"),
        ]),
        "shared_pool_stats": ("shared_pool_stats.csv", [
            ("metric", "TEXT"), ("value", "REAL"),
        ]),
        "parameters": ("parameters.csv", [
            ("name", "TEXT"), ("value", "TEXT"), ("description", "TEXT"),
        ]),
    }

    for table_name, (filename, columns) in file_schemas.items():
        col_defs = ", ".join(f"{c[0]} {c[1]}" for c in columns)
        cur.execute(f"DROP TABLE IF EXISTS {table_name}")
        cur.execute(f"CREATE TABLE {table_name} ({col_defs})")

        filepath = os.path.join(data_dir, filename)
        with open(filepath, newline="") as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            n = len(columns)
            placeholders = ", ".join(["?"] * n)
            for row in reader:
                processed = []
                for i, val in enumerate(row[:n]):
                    col_type = columns[i][1]
                    val = val.strip()
                    if col_type == "REAL":
                        try:
                            processed.append(float(val))
                        except ValueError:
                            processed.append(val)
                    elif col_type == "INTEGER":
                        try:
                            processed.append(int(float(val)))
                        except ValueError:
                            processed.append(val)
                    else:
                        processed.append(val)
                cur.execute(f"INSERT INTO {table_name} VALUES ({placeholders})", processed)

    conn.commit()
    return conn


def compute_metrics(conn):
    """Compute Oracle performance metrics via SQL queries on loaded data."""
    cur = conn.cursor()

    # Sysstat deltas
    cur.execute("""
        SELECT e.statistic_name, e.value - b.value AS delta
        FROM sysstat_end e
        JOIN sysstat_begin b ON e.statistic_name = b.statistic_name
    """)
    deltas = {row[0]: row[1] for row in cur.fetchall()}

    phys_reads = deltas["physical reads"]
    phys_direct = deltas["physical reads direct"]
    consistent = deltas["consistent gets"]
    db_block = deltas["db block gets"]
    bchr = 1.0 - (phys_reads - phys_direct) / (consistent + db_block)

    parse_total = deltas["parse count (total)"]
    parse_hard = deltas["parse count (hard)"]
    spr = (parse_total - parse_hard) / parse_total

    execute_count = deltas["execute count"]
    etpr = 1.0 - (parse_total / execute_count)

    sorts_mem = deltas["sorts (memory)"]
    sorts_disk = deltas["sorts (disk)"]
    imsr = sorts_mem / (sorts_mem + sorts_disk)

    # Library cache hit ratio
    cur.execute("SELECT value FROM shared_pool_stats WHERE metric='library_cache_pins'")
    pins = cur.fetchone()[0]
    cur.execute("SELECT value FROM shared_pool_stats WHERE metric='library_cache_pinhits'")
    pinhits = cur.fetchone()[0]
    lchr = pinhits / pins

    # DB time split
    cur.execute("SELECT value_microseconds FROM time_model WHERE stat_name='DB time'")
    db_time = cur.fetchone()[0]
    cur.execute("SELECT value_microseconds FROM time_model WHERE stat_name='DB CPU'")
    db_cpu = cur.fetchone()[0]
    cpu_pct = db_cpu / db_time
    wait_pct = 1.0 - cpu_pct

    return {
        "buffer_cache_hit_ratio": round(bchr, 4),
        "library_cache_hit_ratio": round(lchr, 4),
        "soft_parse_ratio": round(spr, 4),
        "in_memory_sort_ratio": round(imsr, 4),
        "execute_to_parse_ratio": round(etpr, 4),
        "db_time_cpu_pct": round(cpu_pct, 4),
        "db_time_wait_pct": round(wait_pct, 4),
    }


def analyze_db_cache_advice(conn):
    """Find optimal buffer cache size from advisory curve via knee detection."""
    cur = conn.cursor()
    cur.execute("""
        SELECT CAST(size_for_estimate_mb AS INTEGER) AS size_mb,
               CAST(estd_physical_reads AS INTEGER) AS reads,
               estd_physical_read_factor AS factor
        FROM db_cache_advice
        ORDER BY size_for_estimate_mb
    """)
    data = [{"size_mb": r[0], "reads": r[1], "factor": r[2]} for r in cur.fetchall()]

    current_idx = next(i for i, d in enumerate(data) if abs(d["factor"] - 1.0) < 0.001)

    best_size = data[current_idx]["size_mb"]
    prev_marginal = None
    for i in range(current_idx, len(data) - 1):
        sz_delta = data[i + 1]["size_mb"] - data[i]["size_mb"]
        reads_saved = data[i]["reads"] - data[i + 1]["reads"]
        marginal = reads_saved / sz_delta if sz_delta > 0 else 0

        if prev_marginal is not None and prev_marginal > 0:
            if marginal / prev_marginal < 0.40:
                best_size = data[i]["size_mb"]
                break
            best_size = data[i + 1]["size_mb"]
        else:
            best_size = data[i + 1]["size_mb"]
        prev_marginal = marginal

    return best_size


def analyze_pga_advice(conn):
    """Find optimal PGA target from advisory data."""
    cur = conn.cursor()
    cur.execute("""
        SELECT CAST(pga_target_for_estimate_mb AS INTEGER) AS mb,
               CAST(estd_pga_cache_hit_percentage AS INTEGER) AS hit,
               CAST(estd_overalloc_count AS INTEGER) AS overalloc
        FROM pga_target_advice
        WHERE estd_overalloc_count = 0 AND estd_pga_cache_hit_percentage >= 95
        ORDER BY pga_target_for_estimate_mb
    """)
    candidates = [{"mb": r[0], "hit": r[1]} for r in cur.fetchall()]

    if not candidates:
        cur.execute("""
            SELECT CAST(pga_target_for_estimate_mb AS INTEGER) AS mb, 0 AS hit
            FROM pga_target_advice WHERE estd_overalloc_count = 0
            ORDER BY pga_target_for_estimate_mb
        """)
        candidates = [{"mb": r[0], "hit": r[1]} for r in cur.fetchall()]

    best = candidates[0]
    for i in range(len(candidates) - 1):
        if candidates[i + 1]["hit"] - candidates[i]["hit"] <= 1:
            best = candidates[i]
            break
        best = candidates[i + 1]

    return best["mb"]


def analyze_wait_events(conn):
    """Analyze wait events from loaded data."""
    cur = conn.cursor()
    cur.execute("""
        SELECT TRIM(event), time_waited_micro / 1000000.0 AS time_sec
        FROM system_events ORDER BY time_waited_micro DESC LIMIT 1
    """)
    top = cur.fetchone()

    cur.execute("SELECT SUM(time_waited_micro) / 1000000.0 FROM system_events")
    total = cur.fetchone()[0]

    return {
        "top_event": top[0],
        "top_event_time_sec": round(top[1], 1),
        "total_wait_time_sec": round(total, 1),
    }


def analyze_sql(conn):
    """Analyze SQL statistics for top consumers and literal SQL."""
    cur = conn.cursor()

    cur.execute("SELECT TRIM(sql_id) FROM sql_stats ORDER BY elapsed_time_us DESC LIMIT 3")
    top_sql = [r[0] for r in cur.fetchall()]

    cur.execute("SELECT TRIM(sql_id) FROM sql_stats WHERE version_count > 100")
    literal_sql = [r[0] for r in cur.fetchall()]

    cursor_sharing = "FORCE" if literal_sql else "EXACT"

    return {
        "top_sql_by_elapsed": top_sql,
        "literal_sql_ids": literal_sql,
        "cursor_sharing": cursor_sharing,
    }


def classify_bottleneck(metrics, conn):
    """Classify primary performance bottleneck by correlating metrics and waits."""
    cur = conn.cursor()
    cur.execute("SELECT TRIM(event), time_waited_micro / 1000000.0 FROM system_events")
    events = {r[0]: r[1] for r in cur.fetchall()}
    total_wait = sum(events.values())

    io_wait = events.get("db file sequential read", 0) + events.get("db file scattered read", 0)
    free_buf = events.get("free buffer waits", 0)
    io_and_buf = io_wait + free_buf

    bchr = metrics["buffer_cache_hit_ratio"]

    if bchr < 0.85 and (io_and_buf / total_wait) > 0.50:
        return "buffer_cache"
    elif metrics["db_time_cpu_pct"] > 0.70:
        return "cpu"
    elif metrics["library_cache_hit_ratio"] < 0.85:
        return "shared_pool"
    elif metrics["in_memory_sort_ratio"] < 0.90:
        return "pga"
    else:
        return "io"


def generate_gnuplot_charts(conn, output_dir):
    """Generate advisory curve PNG charts using gnuplot."""
    cur = conn.cursor()

    # DB cache advisory data file
    cur.execute("""
        SELECT CAST(size_for_estimate_mb AS INTEGER),
               CAST(estd_physical_reads AS INTEGER)
        FROM db_cache_advice ORDER BY size_for_estimate_mb
    """)
    cache_dat = os.path.join(output_dir, "cache_data.dat")
    with open(cache_dat, "w") as f:
        for row in cur.fetchall():
            f.write(f"{row[0]} {row[1]}\n")

    cache_png = os.path.join(output_dir, "db_cache_advisory.png")
    cache_script = os.path.join(output_dir, "cache_plot.gp")
    with open(cache_script, "w") as f:
        f.write(f"set terminal pngcairo size 800,600 enhanced\n")
        f.write(f"set output '{cache_png}'\n")
        f.write(f"set title 'Buffer Cache Advisory - Est. Physical Reads vs Cache Size'\n")
        f.write(f"set xlabel 'Buffer Cache Size (MB)'\n")
        f.write(f"set ylabel 'Estimated Physical Reads'\n")
        f.write(f"set grid\n")
        f.write(f"set key off\n")
        f.write(f"plot '{cache_dat}' using 1:2 with linespoints lw 2 pt 7\n")
    subprocess.run(["gnuplot", cache_script], check=True)

    # PGA advisory data file
    cur.execute("""
        SELECT CAST(pga_target_for_estimate_mb AS INTEGER),
               CAST(estd_pga_cache_hit_percentage AS INTEGER)
        FROM pga_target_advice ORDER BY pga_target_for_estimate_mb
    """)
    pga_dat = os.path.join(output_dir, "pga_data.dat")
    with open(pga_dat, "w") as f:
        for row in cur.fetchall():
            f.write(f"{row[0]} {row[1]}\n")

    pga_png = os.path.join(output_dir, "pga_advisory.png")
    pga_script = os.path.join(output_dir, "pga_plot.gp")
    with open(pga_script, "w") as f:
        f.write(f"set terminal pngcairo size 800,600 enhanced\n")
        f.write(f"set output '{pga_png}'\n")
        f.write(f"set title 'PGA Target Advisory - Cache Hit % vs PGA Target'\n")
        f.write(f"set xlabel 'PGA Aggregate Target (MB)'\n")
        f.write(f"set ylabel 'Estimated Cache Hit %'\n")
        f.write(f"set grid\n")
        f.write(f"set key off\n")
        f.write(f"set yrange [0:105]\n")
        f.write(f"plot '{pga_dat}' using 1:2 with linespoints lw 2 pt 7\n")
    subprocess.run(["gnuplot", pga_script], check=True)


def evaluate_reports(correct, report_a_path, report_b_path):
    """Evaluate accuracy of each DBA report against computed ground truth."""
    with open(report_a_path) as f:
        ra = json.load(f)
    with open(report_b_path) as f:
        rb = json.load(f)

    def check_metric(reported, correct_val, tol=0.02):
        return abs(reported - correct_val) <= tol

    def evaluate_single(report, truth):
        incorrect = []
        checks = 0
        correct_count = 0

        # Metric checks
        for m in ["buffer_cache_hit_ratio", "library_cache_hit_ratio",
                   "soft_parse_ratio", "in_memory_sort_ratio",
                   "execute_to_parse_ratio", "db_time_cpu_pct"]:
            checks += 1
            if check_metric(report["metrics"][m], truth["metrics"][m]):
                correct_count += 1
            else:
                incorrect.append(m)

        # Memory recommendation checks
        checks += 1
        if report["memory_recommendations"]["db_cache_size_mb"] in [640, 768, 896]:
            correct_count += 1
        else:
            incorrect.append("db_cache_size_mb")

        checks += 1
        if report["memory_recommendations"]["pga_aggregate_target_mb"] in [768, 1024]:
            correct_count += 1
        else:
            incorrect.append("pga_aggregate_target_mb")

        # SQL tuning checks
        checks += 1
        if report["sql_tuning"]["top_sql_by_elapsed"][:3] == truth["sql_tuning"]["top_sql_by_elapsed"][:3]:
            correct_count += 1
        else:
            incorrect.append("top_sql_by_elapsed")

        checks += 1
        if set(report["sql_tuning"].get("literal_sql_ids", [])) == set(truth["sql_tuning"]["literal_sql_ids"]):
            correct_count += 1
        else:
            incorrect.append("literal_sql_ids")

        checks += 1
        if report["sql_tuning"]["cursor_sharing"].upper() == truth["sql_tuning"]["cursor_sharing"].upper():
            correct_count += 1
        else:
            incorrect.append("cursor_sharing")

        # Primary bottleneck
        checks += 1
        if report["primary_bottleneck"] == truth["primary_bottleneck"]:
            correct_count += 1
        else:
            incorrect.append("primary_bottleneck")

        return {
            "accuracy_score": round(correct_count / checks, 4),
            "incorrect_claims": incorrect,
        }

    eval_a = evaluate_single(ra, correct)
    eval_b = evaluate_single(rb, correct)

    better = "B" if eval_b["accuracy_score"] > eval_a["accuracy_score"] else "A"

    return {
        "report_a": eval_a,
        "report_b": eval_b,
        "better_report": better,
    }


def main():
    data_dir = "/app/perfdata"
    output_dir = "/app/diagnosis"
    db_path = "/app/audit.db"

    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Load data into SQLite
    print("Loading CSV data into SQLite...")
    conn = load_csv_to_sqlite(db_path, data_dir)

    # Step 2: Compute correct metrics
    print("Computing performance metrics...")
    metrics = compute_metrics(conn)

    # Step 3: Memory recommendations from advisory analysis
    db_cache_mb = analyze_db_cache_advice(conn)
    pga_mb = analyze_pga_advice(conn)

    # Step 4: Wait event analysis
    wait_analysis = analyze_wait_events(conn)

    # Step 5: SQL tuning analysis
    sql_analysis = analyze_sql(conn)

    # Step 6: Bottleneck classification
    bottleneck = classify_bottleneck(metrics, conn)

    # Step 7: Generate gnuplot charts
    print("Generating gnuplot advisory charts...")
    generate_gnuplot_charts(conn, output_dir)

    # Build correct results
    correct_results = {
        "metrics": metrics,
        "memory_recommendations": {
            "db_cache_size_mb": db_cache_mb,
            "pga_aggregate_target_mb": pga_mb,
        },
        "wait_analysis": wait_analysis,
        "sql_tuning": sql_analysis,
        "primary_bottleneck": bottleneck,
    }

    # Step 8: Evaluate DBA reports
    print("Evaluating DBA reports...")
    report_eval = evaluate_reports(
        correct_results,
        "/app/reports/report_a.json",
        "/app/reports/report_b.json",
    )

    # Final output
    results = {**correct_results, "report_evaluation": report_eval}

    with open(os.path.join(output_dir, "results.json"), "w") as f:
        json.dump(results, f, indent=2)

    print("Peer review written to /app/diagnosis/results.json")
    print(json.dumps(results, indent=2))

    conn.close()


if __name__ == "__main__":
    main()
