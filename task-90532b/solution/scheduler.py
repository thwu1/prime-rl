#!/usr/bin/env python3

"""
Flux-compatible multi-queue HPC resource scheduler simulator.

Reads a SQLite cluster topology database, TOML queue configuration, and a
Flux-format JSONL event log. Produces a JSON results file recording each
job's final status, allocated ranks, and event timing.
"""

import json
import os
import sqlite3
import tomllib


def parse_idset(s):
    """Parse an idset string like '0-3,8-15' into a sorted list of ints."""
    if not s or not s.strip():
        return []
    result = set()
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            result.update(range(int(lo), int(hi) + 1))
        else:
            result.add(int(part))
    return sorted(result)


def load_cluster(db_path):
    """Load cluster topology from SQLite database."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    nodes = {}
    for rank, cores, gpus in c.execute("SELECT rank, cores, gpus FROM nodes"):
        nodes[rank] = {"cores": cores, "gpus": gpus, "properties": set()}

    for rank, prop in c.execute("SELECT rank, property FROM node_properties"):
        if rank in nodes:
            nodes[rank]["properties"].add(prop)

    conn.close()
    return nodes


def load_queues(path):
    """Load TOML queue configuration."""
    with open(path, "rb") as f:
        data = tomllib.load(f)

    queues = {}
    for name, config in data.get("queues", {}).items():
        q = {
            "name": name,
            "requires": config.get("requires", []),
            "max_duration": None,
            "max_nodes": None,
            "min_nodes": 1,
        }
        policy = config.get("policy", {})
        limits = policy.get("limits", {})
        q["max_duration"] = limits.get("duration")
        range_cfg = limits.get("range", {})
        nnodes_cfg = range_cfg.get("nnodes", {})
        q["min_nodes"] = nnodes_cfg.get("min", 1)
        q["max_nodes"] = nnodes_cfg.get("max")
        queues[name] = q

    default_queue = (
        data.get("policy", {})
        .get("jobspec", {})
        .get("defaults", {})
        .get("system", {})
        .get("queue")
    )
    return queues, default_queue


def load_events(path):
    """Load events from Flux-style JSONL eventlog."""
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            ctx = raw.get("context", {})
            name = raw["name"]
            seq = raw["sequence"]

            if name == "job.submit":
                events.append({
                    "event_id": seq,
                    "type": "submit",
                    "job_id": ctx["job_id"],
                    "queue": ctx.get("queue"),
                    "nnodes": ctx["nnodes"],
                    "ncores_per_node": ctx.get("ncores_per_node", 1),
                    "ngpus_per_node": ctx.get("ngpus_per_node", 0),
                    "duration": ctx.get("duration", 0),
                    "job_requires": ctx.get("constraints", []),
                })
            elif name == "job.complete":
                events.append({
                    "event_id": seq,
                    "type": "complete",
                    "job_id": ctx["job_id"],
                })
            elif name == "resource.drain":
                events.append({
                    "event_id": seq,
                    "type": "drain",
                    "ranks": parse_idset(ctx["targets"]),
                    "reason": ctx.get("reason", ""),
                })
            elif name == "resource.undrain":
                events.append({
                    "event_id": seq,
                    "type": "undrain",
                    "ranks": parse_idset(ctx["targets"]),
                })
    return events


class Scheduler:
    def __init__(self, nodes, queues, default_queue):
        self.nodes = nodes
        self.queues = queues
        self.default_queue = default_queue
        self.allocated = {}          # rank -> job_id
        self.drained = set()
        self.jobs = {}               # job_id -> job record
        self.pending = {qn: [] for qn in queues}

    def _eligible_ranks(self, job):
        """Compute set of ranks eligible for this job."""
        queue = self.queues[job["queue"]]
        eligible = set()
        for rank, node in self.nodes.items():
            if not all(p in node["properties"] for p in queue["requires"]):
                continue
            if not all(p in node["properties"] for p in job["job_requires"]):
                continue
            if node["cores"] < job["ncores_per_node"]:
                continue
            if node["gpus"] < job["ngpus_per_node"]:
                continue
            if rank in self.drained:
                continue
            if rank in self.allocated:
                continue
            eligible.add(rank)
        return eligible

    def _try_allocate(self, job_id):
        """Attempt first-fit allocation. Returns True on success."""
        job = self.jobs[job_id]
        eligible = self._eligible_ranks(job)
        if len(eligible) < job["nnodes"]:
            return False

        chosen = sorted(eligible)[: job["nnodes"]]
        for r in chosen:
            self.allocated[r] = job_id
        job["allocated_ranks"] = chosen
        job["status"] = "running"
        return True

    def _reschedule_pending(self, event_id):
        """Try scheduling head-of-queue jobs across all queues."""
        for qn in self.queues:
            while self.pending[qn]:
                head_id = self.pending[qn][0]
                if self._try_allocate(head_id):
                    self.pending[qn].pop(0)
                    self.jobs[head_id]["scheduled_at_event"] = event_id
                else:
                    break

    def handle_submit(self, event):
        job_id = event["job_id"]
        qn = event.get("queue", self.default_queue)
        queue = self.queues[qn]

        job = {
            "job_id": job_id,
            "queue": qn,
            "nnodes": event["nnodes"],
            "ncores_per_node": event.get("ncores_per_node", 1),
            "ngpus_per_node": event.get("ngpus_per_node", 0),
            "duration": event.get("duration", 0),
            "job_requires": event.get("job_requires", []),
            "status": None,
            "allocated_ranks": None,
            "scheduled_at_event": None,
            "completed_at_event": None,
            "pending_at_event": None,
            "rejected_at_event": None,
            "reason": None,
        }

        # Validate queue limits
        if queue["max_duration"] is not None and job["duration"] > queue["max_duration"]:
            job["status"] = "rejected"
            job["reason"] = "duration_exceeds_limit"
            job["rejected_at_event"] = event["event_id"]
            self.jobs[job_id] = job
            return

        if queue["max_nodes"] is not None and job["nnodes"] > queue["max_nodes"]:
            job["status"] = "rejected"
            job["reason"] = "node_limit_exceeded"
            job["rejected_at_event"] = event["event_id"]
            self.jobs[job_id] = job
            return

        if job["nnodes"] < queue.get("min_nodes", 1):
            job["status"] = "rejected"
            job["reason"] = "below_min_nodes"
            job["rejected_at_event"] = event["event_id"]
            self.jobs[job_id] = job
            return

        self.jobs[job_id] = job

        # FCFS: if queue already has pending jobs, go to end of line
        if self.pending[qn]:
            job["status"] = "pending"
            job["pending_at_event"] = event["event_id"]
            self.pending[qn].append(job_id)
            return

        # Otherwise, try to allocate now
        if self._try_allocate(job_id):
            job["scheduled_at_event"] = event["event_id"]
        else:
            job["status"] = "pending"
            job["pending_at_event"] = event["event_id"]
            self.pending[qn].append(job_id)

    def handle_complete(self, event):
        job_id = event["job_id"]
        job = self.jobs[job_id]

        # Free allocated ranks
        if job["allocated_ranks"]:
            for r in job["allocated_ranks"]:
                if self.allocated.get(r) == job_id:
                    del self.allocated[r]

        job["status"] = "completed"
        job["completed_at_event"] = event["event_id"]

        self._reschedule_pending(event["event_id"])

    def handle_drain(self, event):
        for r in event["ranks"]:
            self.drained.add(r)
        # Drain does NOT trigger rescheduling

    def handle_undrain(self, event):
        for r in event["ranks"]:
            self.drained.discard(r)
        self._reschedule_pending(event["event_id"])

    def process(self, event):
        handler = {
            "submit": self.handle_submit,
            "complete": self.handle_complete,
            "drain": self.handle_drain,
            "undrain": self.handle_undrain,
        }
        handler[event["type"]](event)

    def results(self):
        out = {"jobs": {}}
        for jid, job in self.jobs.items():
            entry = {"status": job["status"]}
            if job["status"] == "completed":
                entry["allocated_ranks"] = sorted(job["allocated_ranks"])
                entry["scheduled_at_event"] = job["scheduled_at_event"]
                entry["completed_at_event"] = job["completed_at_event"]
                if job["pending_at_event"] is not None:
                    entry["pending_at_event"] = job["pending_at_event"]
            elif job["status"] == "rejected":
                entry["reason"] = job["reason"]
                entry["rejected_at_event"] = job["rejected_at_event"]
            out["jobs"][jid] = entry
        return out


def main():
    nodes = load_cluster("/app/cluster.db")
    queues, default_queue = load_queues("/app/queues.toml")
    scheduler = Scheduler(nodes, queues, default_queue)

    events = load_events("/app/eventlog.jsonl")
    for event in events:
        scheduler.process(event)

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/schedule_results.json", "w") as f:
        json.dump(scheduler.results(), f, indent=2)

    print("schedule_results.json written to /app/output/")


if __name__ == "__main__":
    main()
