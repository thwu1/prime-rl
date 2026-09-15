#!/usr/bin/env python3
"""Generate FDB simulation test data for trace forensics task."""

import json
import os
import sqlite3


def mkdir(p):
    os.makedirs(p, exist_ok=True)


def write_file(p, content):
    mkdir(os.path.dirname(p))
    with open(p, "w") as f:
        f.write(content)


def xml_event(attrs):
    parts = [f'{k}="{v}"' for k, v in attrs.items()]
    return "  <Event " + " ".join(parts) + " />"


def make_trace(events_list):
    events_list.sort(key=lambda e: float(e.get("Time", "0")))
    lines = ["<Trace>"]
    for ev in events_list:
        lines.append(xml_event(ev))
    lines.append("</Trace>")
    return "\n".join(lines) + "\n"


# ===== PROCESSES =====
PROCS_8 = [
    {"Machine": "10.0.0.1:4500", "ID": "a1b2c3d4e5f60001", "Roles": "CC,CD"},
    {"Machine": "10.0.0.2:4500", "ID": "a1b2c3d4e5f60002", "Roles": "MS"},
    {"Machine": "10.0.0.3:4500", "ID": "a1b2c3d4e5f60003", "Roles": "TL"},
    {"Machine": "10.0.0.4:4500", "ID": "a1b2c3d4e5f60004", "Roles": "TL"},
    {"Machine": "10.0.0.5:4500", "ID": "a1b2c3d4e5f60005", "Roles": "SS"},
    {"Machine": "10.0.0.6:4500", "ID": "a1b2c3d4e5f60006", "Roles": "SS"},
    {"Machine": "10.0.0.7:4500", "ID": "a1b2c3d4e5f60007", "Roles": "RV"},
    {"Machine": "10.0.0.8:4500", "ID": "a1b2c3d4e5f60008", "Roles": "TS"},
]

PROCS_6 = [
    {"Machine": "10.0.0.1:4500", "ID": "b2c3d4e5f6070001", "Roles": "CC,CD"},
    {"Machine": "10.0.0.2:4500", "ID": "b2c3d4e5f6070002", "Roles": "MS"},
    {"Machine": "10.0.0.3:4500", "ID": "b2c3d4e5f6070003", "Roles": "TL"},
    {"Machine": "10.0.0.4:4500", "ID": "b2c3d4e5f6070004", "Roles": "SS"},
    {"Machine": "10.0.0.5:4500", "ID": "b2c3d4e5f6070005", "Roles": "SS"},
    {"Machine": "10.0.0.6:4500", "ID": "b2c3d4e5f6070006", "Roles": "TS"},
]

RECOVERY_PHASES = [
    "READING_CSTATE", "LOCKING_CSTATE", "RECRUITING",
    "RECOVERY_TRANSACTION", "WRITING_CSTATE", "ACCEPTING_COMMITS",
    "ALL_LOGS_RECRUITED", "STORAGE_RECOVERED", "FULLY_RECOVERED",
]


def ev(typ, sev, time, machine, eid, roles, **kw):
    d = {
        "Type": typ, "Severity": str(sev), "Time": f"{time:.6f}",
        "Machine": machine, "ID": eid, "LogGroup": "default", "Roles": roles,
    }
    d.update({k: str(v) for k, v in kw.items()})
    return d


def prog_starts(t, ver, procs, restarting=False):
    out = []
    for p in procs:
        kw = {"Version": ver, "SourceVersion": "7c2e3a0def456789"}
        if restarting:
            kw["Restarting"] = "1"
        out.append(ev("ProgramStart", 10, t, p["Machine"], p["ID"], p["Roles"], **kw))
    return out


def recovery_evts(t, mp, phases):
    out = []
    for i, ph in enumerate(phases):
        out.append(ev("MasterRecoveryState", 10, t + 0.1 + i * 0.2,
                       mp["Machine"], mp["ID"], "MS", RecoveryState=ph))
    return out


def noise_events(t_start, t_end, procs, count=15):
    """Generate realistic noise events to add trace complexity."""
    out = []
    interval = (t_end - t_start) / max(count, 1)
    for i in range(count):
        t = t_start + i * interval
        p = procs[i % len(procs)]
        if i % 3 == 0:
            out.append(ev("ProcessMetrics", 10, t, p["Machine"], p["ID"], p["Roles"],
                          CPUSeconds=round(0.1 + i * 0.05, 2),
                          MemoryUsage=str(100000000 + i * 5000000),
                          DiskUsage=str(300000000 + i * 10000000),
                          DiskFreeBytes=str(50000000000 - i * 1000000)))
        elif i % 3 == 1:
            out.append(ev("NetworkMetrics", 10, t, p["Machine"], p["ID"], p["Roles"],
                          MbpsSent=round(1.5 + i * 0.3, 1),
                          MbpsReceived=round(2.0 + i * 0.4, 1),
                          RetransmitCount=str(i % 5),
                          ConnectionCount=str(12 + i)))
        else:
            out.append(ev("SlowTask", 10, t, p["Machine"], p["ID"], p["Roles"],
                          Duration=round(0.001 + i * 0.0005, 4),
                          TaskName=f"resolver_commit_{i}",
                          Priority=str(1000 + i * 100)))
    return out


# ========================================================
# RUN 001: FAILING RESTART TEST (upgrade from_7.2.0)
# ========================================================

# Phase 1: old binary 7.2.4, SUCCESS
r1p1 = []
r1p1.extend(prog_starts(1000.0, "7.2.4", PROCS_8))
r1p1.extend(recovery_evts(1000.0, PROCS_8[1], RECOVERY_PHASES))
r1p1.append(ev("TLogJoinedMe", 10, 1000.45, "10.0.0.3:4500", "a1b2c3d4e5f60003", "TL"))
r1p1.append(ev("TLogJoinedMe", 10, 1000.46, "10.0.0.4:4500", "a1b2c3d4e5f60004", "TL"))
r1p1.append(ev("WorkloadSetup", 10, 1002.0, "10.0.0.8:4500", "a1b2c3d4e5f60008", "TS",
               TestName="Cycle", NodeCount=1000))
r1p1.append(ev("WorkloadStart", 10, 1002.5, "10.0.0.8:4500", "a1b2c3d4e5f60008", "TS",
               TestName="Cycle"))
r1p1.extend(noise_events(1003.0, 1024.0, PROCS_8, count=20))
r1p1.append(ev("StorageMetrics", 10, 1015.0, "10.0.0.5:4500", "a1b2c3d4e5f60005", "SS",
               QueryCount=1500, BytesQueried=4500000, MutationCount=800))
r1p1.append(ev("StorageMetrics", 10, 1015.1, "10.0.0.6:4500", "a1b2c3d4e5f60006", "SS",
               QueryCount=1420, BytesQueried=4200000, MutationCount=780))
r1p1.append(ev("TLogMetrics", 10, 1015.2, "10.0.0.3:4500", "a1b2c3d4e5f60003", "TL",
               BytesInput=2500000, BytesDurable=2500000, QueueDiskBytesTotal=0))
r1p1.append(ev("WorkloadCheck", 10, 1025.0, "10.0.0.8:4500", "a1b2c3d4e5f60008", "TS",
               TestName="Cycle", Passed=1))
r1p1.append(ev("WorkloadSetup", 10, 1028.0, "10.0.0.8:4500", "a1b2c3d4e5f60008", "TS",
               TestName="SaveAndKill"))
r1p1.append(ev("SaveAndKillTriggered", 10, 1030.0, "10.0.0.8:4500", "a1b2c3d4e5f60008", "TS",
               RestartInfoFile="simfdb/restartInfo.ini"))
r1p1.append(ev("SimulatedRestart", 10, 1030.5, "10.0.0.1:4500", "a1b2c3d4e5f60001", "CC,CD",
               Reason="SaveAndKill"))

write_file("/app/traces/run_001/phase1.xml", make_trace(r1p1))

# Phase 2: new binary 7.3.0, FAILURE (stuck at RECRUITING)
r1p2 = []
r1p2.extend(prog_starts(2000.0, "7.3.0", PROCS_8, restarting=True))
r1p2.extend(recovery_evts(2000.0, PROCS_8[1], RECOVERY_PHASES[:3]))  # up to RECRUITING
r1p2.append(ev("TLogRestorePersistentState", 10, 2000.6, "10.0.0.3:4500",
               "a1b2c3d4e5f60003", "TL", RecoveryCount=2))
r1p2.append(ev("TLogRestorePersistentState", 10, 2000.61, "10.0.0.4:4500",
               "a1b2c3d4e5f60004", "TL", RecoveryCount=2))
# Injected fault - should be EXCLUDED from real error analysis
r1p2.append(ev("BuggifyInjectedFault", 40, 2002.0, "10.0.0.5:4500",
               "a1b2c3d4e5f60005", "SS", Error="disk_io_error", ErrorIsInjectedFault=1))
# Real errors: TLog rejoin failures
r1p2.append(ev("TLogRejoinError", 40, 2003.0, "10.0.0.3:4500", "a1b2c3d4e5f60003", "TL",
               Error="incompatible_protocol_version", OldVersion="7.2.4", NewVersion="7.3.0",
               Backtrace="0x7f1a2b3c4d5e 0x7f1a2b3c4f00 0x7f1a2b3c5100"))
r1p2.append(ev("TLogRejoinError", 40, 2003.1, "10.0.0.4:4500", "a1b2c3d4e5f60004", "TL",
               Error="incompatible_protocol_version", OldVersion="7.2.4", NewVersion="7.3.0",
               Backtrace="0x7f1a2b3c4d5e 0x7f1a2b3c4f00 0x7f1a2b3c5100"))
# Recovery stalled
r1p2.append(ev("MasterRecoveryStalled", 30, 2005.0, "10.0.0.2:4500", "a1b2c3d4e5f60002", "MS",
               Phase="RECRUITING", Reason="insufficient_tlogs", RecruitedTLogs=0, RequiredTLogs=2))
r1p2.extend(noise_events(2005.5, 2014.0, PROCS_8, count=15))
# Storage servers can't become readable
r1p2.append(ev("StorageServerReadableCheckFailed", 20, 2010.0, "10.0.0.5:4500",
               "a1b2c3d4e5f60005", "SS", Reason="no_committed_version"))
r1p2.append(ev("StorageServerReadableCheckFailed", 20, 2010.1, "10.0.0.6:4500",
               "a1b2c3d4e5f60006", "SS", Reason="no_committed_version"))
# Simulation timeout
r1p2.append(ev("SimulationTimeout", 40, 2015.0, "10.0.0.1:4500", "a1b2c3d4e5f60001", "CC,CD",
               Reason="recovery_timeout", ElapsedTime=15.0))

write_file("/app/traces/run_001/phase2.xml", make_trace(r1p2))

write_file("/app/traces/run_001/metadata.json", json.dumps({
    "test_path": "tests/restarting/from_7.2.0/CycleRestart",
    "seed": 523887594,
    "buggify": True,
}, indent=2))


# ========================================================
# RUN 002: PASSING RESTART TEST (upgrade from_7.2.0)
# ========================================================

# Phase 1: old binary 7.2.4, SUCCESS
r2p1 = []
r2p1.extend(prog_starts(3000.0, "7.2.4", PROCS_8))
r2p1.extend(recovery_evts(3000.0, PROCS_8[1], RECOVERY_PHASES))
r2p1.append(ev("WorkloadSetup", 10, 3002.0, "10.0.0.8:4500", "a1b2c3d4e5f60008", "TS",
               TestName="Storefront", ItemCount=500))
r2p1.append(ev("WorkloadStart", 10, 3002.5, "10.0.0.8:4500", "a1b2c3d4e5f60008", "TS",
               TestName="Storefront"))
r2p1.extend(noise_events(3003.0, 3024.0, PROCS_8, count=18))
r2p1.append(ev("WorkloadCheck", 10, 3025.0, "10.0.0.8:4500", "a1b2c3d4e5f60008", "TS",
               TestName="Storefront", Passed=1))
r2p1.append(ev("WorkloadSetup", 10, 3028.0, "10.0.0.8:4500", "a1b2c3d4e5f60008", "TS",
               TestName="SaveAndKill"))
r2p1.append(ev("SaveAndKillTriggered", 10, 3030.0, "10.0.0.8:4500", "a1b2c3d4e5f60008", "TS",
               RestartInfoFile="simfdb/restartInfo.ini"))
r2p1.append(ev("SimulatedRestart", 10, 3030.5, "10.0.0.1:4500", "a1b2c3d4e5f60001", "CC,CD",
               Reason="SaveAndKill"))

write_file("/app/traces/run_002/phase1.xml", make_trace(r2p1))

# Phase 2: new binary 7.3.0, SUCCESS
r2p2 = []
r2p2.extend(prog_starts(4000.0, "7.3.0", PROCS_8, restarting=True))
r2p2.extend(recovery_evts(4000.0, PROCS_8[1], RECOVERY_PHASES))
r2p2.append(ev("TLogJoinedMe", 10, 4000.4, "10.0.0.3:4500", "a1b2c3d4e5f60003", "TL"))
r2p2.append(ev("TLogJoinedMe", 10, 4000.41, "10.0.0.4:4500", "a1b2c3d4e5f60004", "TL"))
r2p2.append(ev("WorkloadStart", 10, 4002.0, "10.0.0.8:4500", "a1b2c3d4e5f60008", "TS",
               TestName="Storefront"))
r2p2.extend(noise_events(4003.0, 4028.0, PROCS_8, count=18))
r2p2.append(ev("WorkloadCheck", 10, 4030.0, "10.0.0.8:4500", "a1b2c3d4e5f60008", "TS",
               TestName="Storefront", Passed=1))

write_file("/app/traces/run_002/phase2.xml", make_trace(r2p2))

write_file("/app/traces/run_002/metadata.json", json.dumps({
    "test_path": "tests/restarting/from_7.2.0/StorefrontRestart",
    "seed": 847291035,
    "buggify": True,
}, indent=2))


# ========================================================
# RUN 003: FAST TEST (CycleTest, single phase)
# ========================================================

r3 = []
r3.extend(prog_starts(5000.0, "7.3.0", PROCS_6))
r3.extend(recovery_evts(5000.0, PROCS_6[1], RECOVERY_PHASES))
r3.append(ev("TLogJoinedMe", 10, 5000.35, "10.0.0.3:4500", "b2c3d4e5f6070003", "TL"))
r3.append(ev("WorkloadSetup", 10, 5002.0, "10.0.0.6:4500", "b2c3d4e5f6070006", "TS",
             TestName="Cycle", NodeCount=500))
r3.append(ev("WorkloadStart", 10, 5002.5, "10.0.0.6:4500", "b2c3d4e5f6070006", "TS",
             TestName="Cycle"))
r3.extend(noise_events(5003.0, 5009.0, PROCS_6, count=12))
r3.append(ev("WorkloadCheck", 10, 5010.0, "10.0.0.6:4500", "b2c3d4e5f6070006", "TS",
             TestName="Cycle", Passed=1))

write_file("/app/traces/run_003/trace.xml", make_trace(r3))

write_file("/app/traces/run_003/metadata.json", json.dumps({
    "test_path": "tests/fast/CycleTest",
    "seed": 192837465,
    "buggify": False,
}, indent=2))


# ========================================================
# TEST SPECIFICATIONS
# ========================================================

# --- BROKEN UPGRADE PAIR ---
# Bug: Phase 1 missing SaveAndKill workload
write_file("/app/test_specs/broken_upgrade_1.toml", """\
[configuration]
storageEngineExcludeTypes = [3, 5]
tenantModes = ['disabled']
encryptModes = ['disabled']

[[test]]
testTitle = 'UpgradeCycleTest'
clearAfterTest = false

    [[test.workload]]
    testName = 'Cycle'
    transactionsPerSecond = 500.0
    testDuration = 30.0
    nodeCount = 1000
""")

# Bug: Phase 2 has clearAfterTest=true and runSetup=true
write_file("/app/test_specs/broken_upgrade_2.toml", """\
[configuration]
storageEngineExcludeTypes = [3, 5]
tenantModes = ['disabled']
encryptModes = ['disabled']

[[test]]
testTitle = 'UpgradeCycleTest'
clearAfterTest = true
runSetup = true

    [[test.workload]]
    testName = 'Cycle'
    transactionsPerSecond = 500.0
    testDuration = 300.0
    nodeCount = 1000
""")

# --- BROKEN DOWNGRADE PAIR ---
# Bug: Phase 1 missing clearAfterTest=false
write_file("/app/test_specs/broken_downgrade_1.toml", """\
[configuration]
storageEngineExcludeTypes = [3, 5]
tenantModes = ['disabled']

[[test]]
testTitle = 'DowngradeStorefrontTest'

    [[test.workload]]
    testName = 'Storefront'
    transactionsPerSecond = 1000.0
    testDuration = 30.0
    itemCount = 500

    [[test.workload]]
    testName = 'SaveAndKill'
    restartInfoLocation = 'simfdb/restartInfo.ini'
    testDuration = 30.0
""")

# Bug: Phase 2 has SaveAndKill (not allowed)
write_file("/app/test_specs/broken_downgrade_2.toml", """\
[configuration]
storageEngineExcludeTypes = [3, 5]
tenantModes = ['disabled']

[[test]]
testTitle = 'DowngradeStorefrontTest'
runSetup = false

    [[test.workload]]
    testName = 'Storefront'
    transactionsPerSecond = 1000.0
    testDuration = 300.0
    itemCount = 500

    [[test.workload]]
    testName = 'SaveAndKill'
    restartInfoLocation = 'simfdb/restartInfo.ini'
    testDuration = 30.0
""")

# --- BROKEN CYCLE PAIR ---
# Phase 1 is correct
write_file("/app/test_specs/broken_cycle_1.toml", """\
[configuration]
storageEngineExcludeTypes = [3, 5]
tenantModes = ['disabled']
encryptModes = ['disabled']

[[test]]
testTitle = 'CycleRestartTest'
clearAfterTest = false

    [[test.workload]]
    testName = 'Cycle'
    transactionsPerSecond = 500.0
    testDuration = 30.0
    nodeCount = 1000

    [[test.workload]]
    testName = 'SaveAndKill'
    restartInfoLocation = 'simfdb/restartInfo.ini'
    testDuration = 30.0
""")

# Bug: Phase 2 has runSetup=true and inconsistent storageEngineExcludeTypes
write_file("/app/test_specs/broken_cycle_2.toml", """\
[configuration]
storageEngineExcludeTypes = [5]
tenantModes = ['disabled']
encryptModes = ['disabled']

[[test]]
testTitle = 'CycleRestartTest'
runSetup = true

    [[test.workload]]
    testName = 'Cycle'
    transactionsPerSecond = 500.0
    testDuration = 300.0
    nodeCount = 1000
""")

# --- CORRECT STOREFRONT PAIR ---
write_file("/app/test_specs/correct_storefront_1.toml", """\
[configuration]
storageEngineExcludeTypes = [3, 5]
tenantModes = ['disabled']
encryptModes = ['disabled']

[[test]]
testTitle = 'StorefrontRestartTest'
clearAfterTest = false

    [[test.workload]]
    testName = 'Storefront'
    transactionsPerSecond = 1000.0
    testDuration = 30.0
    itemCount = 500
    maxOrderSize = 10

    [[test.workload]]
    testName = 'SaveAndKill'
    restartInfoLocation = 'simfdb/restartInfo.ini'
    testDuration = 30.0
""")

write_file("/app/test_specs/correct_storefront_2.toml", """\
[configuration]
storageEngineExcludeTypes = [3, 5]
tenantModes = ['disabled']
encryptModes = ['disabled']

[[test]]
testTitle = 'StorefrontRestartTest'
runSetup = false

    [[test.workload]]
    testName = 'Storefront'
    transactionsPerSecond = 1000.0
    testDuration = 300.0
    itemCount = 500
    maxOrderSize = 10
""")


# ========================================================
# SQLITE KNOWLEDGE DATABASE
# ========================================================

def create_knowledge_db():
    db_path = "/app/fdb_knowledge.db"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Binary registry: version -> path, protocol version, metadata
    c.execute("""CREATE TABLE binary_registry (
        version TEXT PRIMARY KEY,
        path TEXT NOT NULL,
        protocol_version TEXT NOT NULL,
        release_date TEXT,
        branch TEXT
    )""")

    binary_data = [
        ("7.1.0", "/opt/fdb/bin/fdbserver-7.1.0", "0x0FDB00B071000000", "2022-06-15", "release-7.1"),
        ("7.1.3", "/opt/fdb/bin/fdbserver-7.1.3", "0x0FDB00B071030000", "2022-08-10", "release-7.1"),
        ("7.1.5", "/opt/fdb/bin/fdbserver-7.1.5", "0x0FDB00B071050000", "2022-09-20", "release-7.1"),
        ("7.2.0", "/opt/fdb/bin/fdbserver-7.2.0", "0x0FDB00B072000000", "2023-01-10", "release-7.2"),
        ("7.2.2", "/opt/fdb/bin/fdbserver-7.2.2", "0x0FDB00B072020000", "2023-03-05", "release-7.2"),
        ("7.2.4", "/opt/fdb/bin/fdbserver-7.2.4", "0x0FDB00B072040000", "2023-04-18", "release-7.2"),
        ("7.3.0", "/opt/fdb/bin/fdbserver-7.3.0", "0x0FDB00B073000000", "2023-08-01", "release-7.3"),
    ]
    c.executemany("INSERT INTO binary_registry VALUES (?, ?, ?, ?, ?)", binary_data)

    # Protocol compatibility matrix
    c.execute("""CREATE TABLE protocol_compat (
        from_protocol TEXT NOT NULL,
        to_protocol TEXT NOT NULL,
        compatible INTEGER NOT NULL,
        notes TEXT,
        PRIMARY KEY (from_protocol, to_protocol)
    )""")

    compat_data = [
        # Same major.minor line - compatible
        ("0x0FDB00B071000000", "0x0FDB00B071030000", 1, "Same 7.1.x line"),
        ("0x0FDB00B071000000", "0x0FDB00B071050000", 1, "Same 7.1.x line"),
        ("0x0FDB00B071030000", "0x0FDB00B071050000", 1, "Same 7.1.x line"),
        ("0x0FDB00B072000000", "0x0FDB00B072020000", 1, "Same 7.2.x line"),
        ("0x0FDB00B072000000", "0x0FDB00B072040000", 1, "Same 7.2.x line"),
        ("0x0FDB00B072020000", "0x0FDB00B072040000", 1, "Same 7.2.x line"),
        # Cross-generation - incompatible
        ("0x0FDB00B071050000", "0x0FDB00B072000000", 0, "Cross-gen: 7.1->7.2 incompatible protocol"),
        ("0x0FDB00B071050000", "0x0FDB00B072040000", 0, "Cross-gen: 7.1->7.2 incompatible protocol"),
        ("0x0FDB00B072000000", "0x0FDB00B073000000", 0, "Cross-gen: 7.2->7.3 incompatible protocol"),
        ("0x0FDB00B072040000", "0x0FDB00B073000000", 0, "Cross-gen: 7.2->7.3 incompatible protocol"),
        ("0x0FDB00B073000000", "0x0FDB00B072040000", 0, "Cross-gen: 7.3->7.2 incompatible protocol"),
        ("0x0FDB00B073000000", "0x0FDB00B072000000", 0, "Cross-gen: 7.3->7.2 incompatible protocol"),
    ]
    c.executemany("INSERT INTO protocol_compat VALUES (?, ?, ?, ?)", compat_data)

    # Known failure signatures for classification
    c.execute("""CREATE TABLE failure_signatures (
        id INTEGER PRIMARY KEY,
        event_type TEXT NOT NULL,
        error_code TEXT,
        category TEXT NOT NULL,
        severity_class TEXT NOT NULL,
        root_cause_template TEXT,
        resolution TEXT
    )""")

    sig_data = [
        (1, "TLogRejoinError", "incompatible_protocol_version", "protocol_mismatch", "critical",
         "TLog process running protocol {old_proto} cannot rejoin cluster running protocol {new_proto}. "
         "Old and new binaries use incompatible wire protocols.",
         "Ensure restart test uses the SaveAndKill+checkpoint mechanism for cross-version testing"),
        (2, "StorageServerReadableCheckFailed", "no_committed_version", "stale_storage", "warning",
         "Storage server has no committed version due to upstream recovery failure",
         "Resolve upstream recovery failure first"),
        (3, "SimulationTimeout", "recovery_timeout", "timeout", "critical",
         "Simulation timed out waiting for recovery to complete after {elapsed}s",
         "Investigate why recovery is stalled - check TLog/resolver availability"),
        (4, "MasterRecoveryStalled", "insufficient_tlogs", "recruitment_failure", "critical",
         "Master cannot recruit minimum {required} TLogs (only {recruited} available) for recovery",
         "Check TLog process availability and protocol compatibility"),
        (5, "BuggifyInjectedFault", None, "injected_fault", "ignore",
         "Deliberately injected fault for simulation testing - must be excluded from error analysis",
         "No action needed - simulation testing artifact"),
    ]
    c.executemany("INSERT INTO failure_signatures VALUES (?, ?, ?, ?, ?, ?, ?)", sig_data)

    # Recovery requirements per role
    c.execute("""CREATE TABLE recovery_requirements (
        role TEXT NOT NULL,
        role_code TEXT NOT NULL,
        min_count INTEGER NOT NULL,
        description TEXT,
        PRIMARY KEY (role, role_code)
    )""")

    reqs = [
        ("TransactionLog", "TL", 2, "Minimum 2 TLogs required for default triple replication policy"),
        ("StorageServer", "SS", 1, "At least 1 storage server for data serving"),
        ("Master", "MS", 1, "Exactly 1 master/sequencer for transaction ordering"),
        ("ClusterController", "CC", 1, "Exactly 1 cluster controller for coordination"),
        ("Resolver", "RV", 1, "At least 1 resolver for read-write conflict detection"),
    ]
    c.executemany("INSERT INTO recovery_requirements VALUES (?, ?, ?, ?)", reqs)

    conn.commit()
    conn.close()


create_knowledge_db()


# ========================================================
# ORCHESTRATOR INPUT
# (binary paths must be resolved from the database)
# ========================================================

write_file("/app/orchestrator_input.json", json.dumps({
    "scenarios": [
        {
            "test_path": "tests/restarting/from_7.2.0/CycleRestart",
            "seed": 523887594,
            "buggify": True,
            "source_version_line": "7.2",
            "target_version_line": "7.3",
        },
        {
            "test_path": "tests/restarting/to_7.2.0/StorefrontDowngrade",
            "seed": 847291035,
            "buggify": True,
            "source_version_line": "7.2",
            "target_version_line": "7.3",
        },
    ]
}, indent=2))


# ========================================================
# OUTPUT SCHEMAS
# ========================================================

output_schemas = {
    "run_analysis": {
        "description": "Schema for run_NNN_analysis.json. One file per run directory.",
        "type": "object",
        "required": ["run_id", "test_result", "phases"],
        "properties": {
            "run_id": {
                "type": "string",
                "description": "Run directory name (e.g., 'run_001')"
            },
            "test_result": {
                "type": "string",
                "enum": ["PASSED", "FAILED"],
                "description": "Overall test outcome determined from trace analysis"
            },
            "metadata": {
                "type": "object",
                "description": "Original metadata.json contents"
            },
            "phases": {
                "type": "array",
                "description": "Per-phase analysis. Restart tests have 2 phases; fast tests have 1.",
                "items": {
                    "type": "object",
                    "required": [
                        "phase", "binary_version", "processes",
                        "recovery_states", "final_recovery_state",
                        "recovery_completed", "errors", "saveandkill_triggered"
                    ],
                    "properties": {
                        "phase": {
                            "type": "integer",
                            "description": "1-indexed phase number"
                        },
                        "trace_file": {
                            "type": "string",
                            "description": "Trace XML filename for this phase"
                        },
                        "binary_version": {
                            "type": "string",
                            "description": "FDB server version string used in this phase"
                        },
                        "is_restarting": {
                            "type": "boolean",
                            "description": "Whether this phase is a restart continuation"
                        },
                        "processes": {
                            "type": "array",
                            "description": "Unique processes observed in trace events",
                            "items": {
                                "type": "object",
                                "required": ["machine", "roles"],
                                "properties": {
                                    "machine": {
                                        "type": "string",
                                        "description": "Process address (host:port)"
                                    },
                                    "id": {
                                        "type": "string",
                                        "description": "Process identifier"
                                    },
                                    "roles": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "FDB roles assigned to this process"
                                    }
                                }
                            }
                        },
                        "recovery_states": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Ordered sequence of recovery state machine transitions"
                        },
                        "final_recovery_state": {
                            "type": "string",
                            "description": "Last recovery state observed in this phase"
                        },
                        "recovery_completed": {
                            "type": "boolean",
                            "description": "Whether recovery reached the terminal successful state"
                        },
                        "errors": {
                            "type": "array",
                            "description": "Genuine error events, excluding deliberately injected simulation faults",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string", "description": "Event type name"},
                                    "severity": {"type": "integer"},
                                    "machine": {"type": "string"},
                                    "time": {"type": "number"},
                                    "error_code": {"type": "string"}
                                }
                            }
                        },
                        "workloads": {
                            "type": "array",
                            "description": "Workload activity detected in this phase"
                        },
                        "saveandkill_triggered": {
                            "type": "boolean",
                            "description": "Whether a save-and-kill checkpoint was triggered in this phase"
                        }
                    }
                }
            },
            "root_cause": {
                "type": "object",
                "description": "Root cause analysis for failed runs. Must include protocol version data from the knowledge database.",
                "required": ["category", "description", "protocol_versions"],
                "properties": {
                    "category": {"type": "string", "description": "Error category from failure_signatures table"},
                    "description": {"type": "string", "description": "Narrative explanation of the failure chain"},
                    "affected_processes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Addresses of processes involved in the failure"
                    },
                    "impact": {"type": "string", "description": "Impact on cluster recovery"},
                    "protocol_versions": {
                        "type": "object",
                        "description": "Protocol version analysis from the knowledge database",
                        "required": ["old", "new", "compatible"],
                        "properties": {
                            "old": {"type": "string", "description": "Protocol version hex identifier of the old binary (from binary_registry)"},
                            "new": {"type": "string", "description": "Protocol version hex identifier of the new binary (from binary_registry)"},
                            "compatible": {"type": "boolean", "description": "Compatibility status from protocol_compat table"}
                        }
                    }
                }
            }
        }
    },
    "spec_validation": {
        "description": "Schema for spec_validation.json. Audit of restart test TOML spec pairs.",
        "type": "object",
        "required": ["specs"],
        "properties": {
            "specs": {
                "type": "array",
                "description": "Validation result per spec pair",
                "items": {
                    "type": "object",
                    "required": ["name", "valid", "errors"],
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Base name of the spec pair (e.g., 'broken_upgrade')"
                        },
                        "phase1_file": {"type": "string"},
                        "phase2_file": {"type": "string"},
                        "valid": {
                            "type": "boolean",
                            "description": "Whether the pair conforms to FDB restart test conventions"
                        },
                        "errors": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Descriptions of convention violations found"
                        }
                    }
                }
            }
        }
    },
    "reproduction_commands": {
        "description": "Schema for reproduction_commands.json. Binary paths must be resolved from the binary_registry table in fdb_knowledge.db.",
        "type": "object",
        "required": ["commands"],
        "properties": {
            "commands": {
                "type": "array",
                "description": "One entry per scenario from orchestrator_input.json",
                "items": {
                    "type": "object",
                    "required": ["test_path", "test_type", "phase1", "phase2"],
                    "properties": {
                        "test_path": {"type": "string"},
                        "test_type": {
                            "type": "string",
                            "enum": ["upgrade", "downgrade"],
                            "description": "Direction derived from the test path naming convention"
                        },
                        "phase1": {
                            "type": "object",
                            "required": ["binary", "seed", "restarting", "command"],
                            "properties": {
                                "binary": {"type": "string", "description": "Path to fdbserver binary resolved from binary_registry"},
                                "seed": {"type": "integer", "description": "Simulation seed from the scenario"},
                                "buggify": {"type": "boolean"},
                                "restarting": {"type": "boolean", "description": "Must be false for phase 1"},
                                "command": {"type": "string", "description": "Complete fdbserver -r simulation command line"}
                            }
                        },
                        "phase2": {
                            "type": "object",
                            "required": ["binary", "seed", "restarting", "command"],
                            "properties": {
                                "binary": {"type": "string", "description": "Path to fdbserver binary resolved from binary_registry"},
                                "seed": {"type": "integer", "description": "Must equal phase1.seed + 1"},
                                "buggify": {"type": "boolean"},
                                "restarting": {"type": "boolean", "description": "Must be true for phase 2"},
                                "command": {"type": "string", "description": "Complete fdbserver -r simulation command line including --restarting"}
                            }
                        }
                    }
                }
            }
        }
    }
}

write_file("/app/output_schemas.json", json.dumps(output_schemas, indent=2))


print("Data generation complete.")
