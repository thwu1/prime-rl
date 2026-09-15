
import asyncio
import json
import re
import sqlite3
import time
import uuid
from collections import OrderedDict

import yaml

from .models import ErrorKind, TaskResult
from .registry import TaskRegistry


class WorkflowEngine:
    def __init__(self, db_path: str, registry: TaskRegistry):
        self.db_path = db_path
        self.registry = registry
        self._init_db()

    # ------------------------------------------------------------------
    # Database setup
    # ------------------------------------------------------------------
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                workflow_json TEXT NOT NULL,
                cluster_json TEXT NOT NULL,
                variables_json TEXT NOT NULL,
                target_nodes_json TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS task_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                cluster_task_index INTEGER NOT NULL,
                node_name TEXT NOT NULL,
                task_index INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                error_message TEXT DEFAULT '',
                UNIQUE(job_id, cluster_task_index, node_name, task_index),
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            );
            """
        )
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Workflow loading
    # ------------------------------------------------------------------
    def load_workflow(self, path: str) -> dict:
        with open(path) as f:
            return yaml.safe_load(f)

    # ------------------------------------------------------------------
    # Variable handling
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_variables(workflow: dict, user_vars: dict | None) -> dict:
        variables = {}
        for vdef in workflow.get("variables", []):
            variables[vdef["name"]] = vdef.get("default", "")
        if user_vars:
            variables.update(user_vars)
        return variables

    @classmethod
    def _substitute(cls, obj, variables: dict):
        if isinstance(obj, str):
            return re.sub(
                r"\{\{(\w+)\}\}",
                lambda m: str(variables.get(m.group(1).strip(), m.group(0))),
                obj,
            )
        if isinstance(obj, dict):
            return {k: cls._substitute(v, variables) for k, v in obj.items()}
        if isinstance(obj, list):
            return [cls._substitute(v, variables) for v in obj]
        return obj

    # ------------------------------------------------------------------
    # Job creation
    # ------------------------------------------------------------------
    def create_job(
        self,
        workflow: dict,
        cluster: dict,
        variables: dict | None = None,
        target_nodes: list | None = None,
    ) -> str:
        job_id = str(uuid.uuid4())
        resolved = self._resolve_variables(workflow, variables)
        wf_sub = self._substitute(workflow, resolved)

        nodes = cluster["nodes"]
        if target_nodes:
            nodes = [n for n in nodes if n["name"] in target_nodes]

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO jobs "
            "(id, workflow_json, cluster_json, variables_json, target_nodes_json, status, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                job_id,
                json.dumps(wf_sub),
                json.dumps(cluster),
                json.dumps(resolved),
                json.dumps(target_nodes),
                "pending",
                time.time(),
            ),
        )

        for ct_idx, ct in enumerate(wf_sub.get("cluster_tasks", [])):
            for node in nodes:
                for t_idx in range(len(ct.get("node_tasks", []))):
                    conn.execute(
                        "INSERT INTO task_states "
                        "(job_id, cluster_task_index, node_name, task_index, status, attempts, error_message) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (job_id, ct_idx, node["name"], t_idx, "pending", 0, ""),
                    )

        conn.commit()
        conn.close()
        return job_id

    # ------------------------------------------------------------------
    # Job execution / resume
    # ------------------------------------------------------------------
    async def run_job(self, job_id: str) -> dict:
        return await self._execute_job(job_id)

    async def resume_job(self, job_id: str) -> dict:
        return await self._execute_job(job_id)

    async def _execute_job(self, job_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT workflow_json, cluster_json, variables_json, target_nodes_json "
            "FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        if not row:
            conn.close()
            raise ValueError(f"Job {job_id} not found")

        workflow = json.loads(row[0])
        cluster = json.loads(row[1])
        target_nodes_list = json.loads(row[3]) if row[3] else None

        nodes = cluster["nodes"]
        if target_nodes_list:
            nodes = [n for n in nodes if n["name"] in target_nodes_list]

        conn.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
        conn.commit()

        completed_tasks = 0
        failed_tasks = 0
        job_status = "completed"
        job_halted = False

        for ct_idx, ct in enumerate(workflow.get("cluster_tasks", [])):
            if job_halted:
                break

            cu = ct.get("concurrency_unit", "all")
            cl = ct.get("concurrency_limit", 1)
            node_tasks = ct.get("node_tasks", [])

            if cu == "zone":
                zone_map: OrderedDict[str, list] = OrderedDict()
                for n in nodes:
                    zone_map.setdefault(n["zone"], []).append(n)
                batches = list(zone_map.values())
            else:
                batches = [list(nodes)]

            for batch in batches:
                if job_halted:
                    break

                sem = asyncio.Semaphore(cl)

                async def _process_node(
                    node,
                    _sem=sem,
                    _ct_idx=ct_idx,
                    _node_tasks=node_tasks,
                ):
                    nonlocal completed_tasks, failed_tasks, job_halted, job_status
                    async with _sem:
                        for t_idx, td in enumerate(_node_tasks):
                            if job_halted:
                                return

                            cur = conn.execute(
                                "SELECT status FROM task_states "
                                "WHERE job_id=? AND cluster_task_index=? "
                                "AND node_name=? AND task_index=?",
                                (job_id, _ct_idx, node["name"], t_idx),
                            ).fetchone()
                            if cur and cur[0] == "completed":
                                completed_tasks += 1
                                continue

                            ttype = td.get("type")
                            if ttype == "wait_for_condition":
                                ok = await self._run_condition(
                                    node, td, job_id, _ct_idx, t_idx, conn
                                )
                            else:
                                ok = await self._run_task(
                                    node, td, job_id, _ct_idx, t_idx, conn
                                )

                            if ok:
                                completed_tasks += 1
                            else:
                                failed_tasks += 1
                                job_halted = True
                                job_status = "failed"
                                return

                await asyncio.gather(*[_process_node(n) for n in batch])

        conn.execute("UPDATE jobs SET status=? WHERE id=?", (job_status, job_id))
        conn.commit()
        conn.close()
        return {
            "status": job_status,
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks,
        }

    # ------------------------------------------------------------------
    # Condition execution
    # ------------------------------------------------------------------
    async def _run_condition(self, node, td, job_id, ct_idx, t_idx, conn) -> bool:
        cond_name = td.get("condition", "")
        params = td.get("params", {})
        timeout = float(params.get("timeout_seconds", 60))
        poll_iv = float(params.get("poll_interval_seconds", 1))
        win = float(params.get("success_window_seconds", 0))

        handler_key = f"condition:{cond_name}"
        if not self.registry.has_handler(handler_key):
            conn.execute(
                "UPDATE task_states SET status='completed' "
                "WHERE job_id=? AND cluster_task_index=? AND node_name=? AND task_index=?",
                (job_id, ct_idx, node["name"], t_idx),
            )
            conn.commit()
            return True

        handler = self.registry.get_handler(handler_key)
        conn.execute(
            "UPDATE task_states SET status='in_progress' "
            "WHERE job_id=? AND cluster_task_index=? AND node_name=? AND task_index=?",
            (job_id, ct_idx, node["name"], t_idx),
        )
        conn.commit()

        loop = asyncio.get_event_loop()
        t0 = loop.time()
        win_start = None

        while True:
            if loop.time() - t0 >= timeout:
                conn.execute(
                    "UPDATE task_states SET status='failed', error_message='timeout' "
                    "WHERE job_id=? AND cluster_task_index=? AND node_name=? AND task_index=?",
                    (job_id, ct_idx, node["name"], t_idx),
                )
                conn.commit()
                return False

            try:
                result = await handler(node, params, {})
            except Exception:
                result = TaskResult.fail(ErrorKind.RECOVERABLE, "exception in condition")

            if result.success:
                if win <= 0:
                    conn.execute(
                        "UPDATE task_states SET status='completed' "
                        "WHERE job_id=? AND cluster_task_index=? AND node_name=? AND task_index=?",
                        (job_id, ct_idx, node["name"], t_idx),
                    )
                    conn.commit()
                    return True
                if win_start is None:
                    win_start = loop.time()
                elif loop.time() - win_start >= win:
                    conn.execute(
                        "UPDATE task_states SET status='completed' "
                        "WHERE job_id=? AND cluster_task_index=? AND node_name=? AND task_index=?",
                        (job_id, ct_idx, node["name"], t_idx),
                    )
                    conn.commit()
                    return True
            else:
                win_start = None

            await asyncio.sleep(poll_iv)

    # ------------------------------------------------------------------
    # Regular task execution
    # ------------------------------------------------------------------
    async def _run_task(self, node, td, job_id, ct_idx, t_idx, conn) -> bool:
        ttype = td.get("type")
        params = td.get("params", {})
        max_retries = td.get("retries", 3)

        handler = self.registry.get_handler(ttype)

        conn.execute(
            "UPDATE task_states SET status='in_progress' "
            "WHERE job_id=? AND cluster_task_index=? AND node_name=? AND task_index=?",
            (job_id, ct_idx, node["name"], t_idx),
        )
        conn.commit()

        for attempt in range(max_retries + 1):
            try:
                result = await handler(node, params, {"attempt": attempt})
            except Exception as exc:
                result = TaskResult.fail(ErrorKind.RECOVERABLE, str(exc))

            if result.success:
                conn.execute(
                    "UPDATE task_states SET status='completed', attempts=? "
                    "WHERE job_id=? AND cluster_task_index=? AND node_name=? AND task_index=?",
                    (attempt + 1, job_id, ct_idx, node["name"], t_idx),
                )
                conn.commit()
                return True

            if result.error_kind == ErrorKind.UNRECOVERABLE:
                conn.execute(
                    "UPDATE task_states SET status='failed', attempts=?, error_message=? "
                    "WHERE job_id=? AND cluster_task_index=? AND node_name=? AND task_index=?",
                    (attempt + 1, result.message, job_id, ct_idx, node["name"], t_idx),
                )
                conn.commit()
                return False

            if attempt == max_retries:
                conn.execute(
                    "UPDATE task_states SET status='failed', attempts=?, error_message=? "
                    "WHERE job_id=? AND cluster_task_index=? AND node_name=? AND task_index=?",
                    (attempt + 1, result.message, job_id, ct_idx, node["name"], t_idx),
                )
                conn.commit()
                return False

        return False  # unreachable

    # ------------------------------------------------------------------
    # Status query
    # ------------------------------------------------------------------
    def get_job_status(self, job_id: str) -> dict:
        conn = sqlite3.connect(self.db_path)
        jrow = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        trows = conn.execute(
            "SELECT cluster_task_index, node_name, task_index, status, attempts, error_message "
            "FROM task_states WHERE job_id=? ORDER BY cluster_task_index, task_index",
            (job_id,),
        ).fetchall()
        conn.close()
        return {
            "job_status": jrow[0] if jrow else None,
            "tasks": [
                {
                    "cluster_task_index": r[0],
                    "node": r[1],
                    "task_index": r[2],
                    "status": r[3],
                    "attempts": r[4],
                    "error_message": r[5],
                }
                for r in trows
            ],
        }
