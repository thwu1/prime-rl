#!/usr/bin/env python3
"""Generate SQLite database with microservice trace span data.

"""
import sqlite3

BASE = 1700000000000000
DB = "/app/traces.db"


def main():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE spans (
            trace_id TEXT NOT NULL,
            span_id TEXT NOT NULL,
            operation_name TEXT NOT NULL,
            process_id TEXT NOT NULL,
            start_time_us INTEGER NOT NULL,
            duration_us INTEGER NOT NULL,
            PRIMARY KEY (trace_id, span_id)
        );
        CREATE TABLE span_references (
            trace_id TEXT NOT NULL,
            span_id TEXT NOT NULL,
            ref_type TEXT NOT NULL,
            parent_trace_id TEXT NOT NULL,
            parent_span_id TEXT NOT NULL
        );
        CREATE TABLE processes (
            trace_id TEXT NOT NULL,
            process_id TEXT NOT NULL,
            service_name TEXT NOT NULL,
            PRIMARY KEY (trace_id, process_id)
        );
        CREATE INDEX idx_refs_trace ON span_references(trace_id);
        CREATE INDEX idx_spans_trace ON spans(trace_id);
    """)

    def s(tid, sid, op, pid, off, dur):
        c.execute("INSERT INTO spans VALUES (?,?,?,?,?,?)",
                  (tid, sid, op, pid, BASE + off, dur))

    def r(tid, sid, rtype, psid):
        c.execute("INSERT INTO span_references VALUES (?,?,?,?,?)",
                  (tid, sid, rtype, tid, psid))

    def p(tid, pid, svc):
        c.execute("INSERT INTO processes VALUES (?,?,?)",
                  (tid, pid, svc))

    # t001: gateway -> auth -> userdb (linear chain)
    s("t001", "s1a", "handleRequest", "p1", 0, 100000)
    s("t001", "s1b", "validate", "p2", 10000, 30000)
    s("t001", "s1c", "lookup", "p3", 15000, 20000)
    r("t001", "s1b", "CHILD_OF", "s1a")
    r("t001", "s1c", "CHILD_OF", "s1b")
    p("t001", "p1", "gateway")
    p("t001", "p2", "auth")
    p("t001", "p3", "userdb")

    # t002: gateway -> serviceA, serviceB (parallel children)
    s("t002", "s2a", "handleRequest", "p1", 0, 200000)
    s("t002", "s2b", "fetch", "p2", 20000, 60000)
    s("t002", "s2c", "fetch", "p3", 30000, 150000)
    r("t002", "s2b", "CHILD_OF", "s2a")
    r("t002", "s2c", "CHILD_OF", "s2a")
    p("t002", "p1", "gateway")
    p("t002", "p2", "serviceA")
    p("t002", "p3", "serviceB")

    # t003: gateway -> backend -> db (timing anomaly in child durations)
    s("t003", "s3a", "handleRequest", "p1", 0, 100000)
    s("t003", "s3b", "process", "p2", 10000, 110000)
    s("t003", "s3c", "query", "p3", 20000, 85000)
    r("t003", "s3b", "CHILD_OF", "s3a")
    r("t003", "s3c", "CHILD_OF", "s3b")
    p("t003", "p1", "gateway")
    p("t003", "p2", "backend")
    p("t003", "p3", "db")

    # t004: gateway -> analytics, auth, backend (mixed reference types)
    s("t004", "s4a", "handleRequest", "p1", 0, 150000)
    s("t004", "s4b", "log", "p2", 5000, 80000)
    s("t004", "s4c", "validate", "p3", 10000, 40000)
    s("t004", "s4d", "process", "p4", 60000, 70000)
    r("t004", "s4b", "FOLLOWS_FROM", "s4a")
    r("t004", "s4c", "CHILD_OF", "s4a")
    r("t004", "s4d", "CHILD_OF", "s4a")
    p("t004", "p1", "gateway")
    p("t004", "p2", "analytics")
    p("t004", "p3", "auth")
    p("t004", "p4", "backend")

    # t005: deep 5-level fan-out
    s("t005", "s5a", "handleRequest", "p1", 0, 300000)
    s("t005", "s5b", "process", "p2", 10000, 280000)
    s("t005", "s5c", "call", "p3", 20000, 100000)
    s("t005", "s5d", "call", "p4", 150000, 120000)
    s("t005", "s5e", "query", "p5", 30000, 80000)
    s("t005", "s5f", "compute", "p6", 160000, 90000)
    r("t005", "s5b", "CHILD_OF", "s5a")
    r("t005", "s5c", "CHILD_OF", "s5b")
    r("t005", "s5d", "CHILD_OF", "s5b")
    r("t005", "s5e", "CHILD_OF", "s5c")
    r("t005", "s5f", "CHILD_OF", "s5d")
    p("t005", "p1", "gateway")
    p("t005", "p2", "serviceA")
    p("t005", "p3", "serviceB")
    p("t005", "p4", "serviceD")
    p("t005", "p5", "serviceC")
    p("t005", "p6", "serviceE")

    # t006: two-level
    s("t006", "s6a", "handleRequest", "p1", 0, 120000)
    s("t006", "s6b", "process", "p2", 15000, 90000)
    r("t006", "s6b", "CHILD_OF", "s6a")
    p("t006", "p1", "gateway")
    p("t006", "p2", "backend")

    # t007: three children sequential
    s("t007", "s7a", "handleRequest", "p1", 0, 140000)
    s("t007", "s7b", "validate", "p2", 10000, 30000)
    s("t007", "s7c", "process", "p3", 50000, 70000)
    r("t007", "s7b", "CHILD_OF", "s7a")
    r("t007", "s7c", "CHILD_OF", "s7a")
    p("t007", "p1", "gateway")
    p("t007", "p2", "auth")
    p("t007", "p3", "backend")

    # t008: two-level
    s("t008", "s8a", "handleRequest", "p1", 0, 160000)
    s("t008", "s8b", "process", "p2", 25000, 110000)
    r("t008", "s8b", "CHILD_OF", "s8a")
    p("t008", "p1", "gateway")
    p("t008", "p2", "backend")

    # t009: three children sequential
    s("t009", "s9a", "handleRequest", "p1", 0, 180000)
    s("t009", "s9b", "validate", "p2", 15000, 50000)
    s("t009", "s9c", "process", "p3", 70000, 100000)
    r("t009", "s9b", "CHILD_OF", "s9a")
    r("t009", "s9c", "CHILD_OF", "s9a")
    p("t009", "p1", "gateway")
    p("t009", "p2", "auth")
    p("t009", "p3", "backend")

    # t010: two-level long
    s("t010", "s10a", "handleRequest", "p1", 0, 250000)
    s("t010", "s10b", "process", "p2", 40000, 170000)
    r("t010", "s10b", "CHILD_OF", "s10a")
    p("t010", "p1", "gateway")
    p("t010", "p2", "backend")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
