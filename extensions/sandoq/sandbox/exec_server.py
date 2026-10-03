#!/usr/bin/env python3
"""Structured command-exec server backed by a persistent bash shell.

Endpoints
  POST /exec        {"cmd": "...", "timeout": 60}
                    -> {stdout, stderr, exit_code, duration_s, timed_out, shell_died}
  POST /reset       -> restart the shell (fresh cwd/env). Returns {"status":"reset"}.
  GET  /healthz     -> {"status":"ok","shell_alive":bool}

  # prime-rl operation surface (used by the sandoq shim; it falls back to
  # base64-over-/exec when these are absent, so older images still work):
  POST /upload      {"path":"...","content_b64":"..."} -> {"ok":true,"size":N}
  GET  /read_file   ?path=...                          -> {"content_b64":"...","size":N} | 404
  POST /start_job   {"cmd":"...","env":{...}?,"cwd":"..."?} -> {"job_id":"..."}
  GET  /job/{id}    -> {"job_id","completed","exit_code","stdout","stderr"} | 404

Why a persistent shell: every /exec runs in ONE long-lived `bash`, so state
(cwd, env vars, shell functions) persists across calls -- same statefulness as an
interactive terminal, but with clean, structured results.

Why background jobs are separate processes: /exec serializes on one shell, so a
long-running command (e.g. an agent, or PythonEnv's persistent worker launched
from `start_command`) would block it. /start_job runs the command detached in its
own process group, redirecting stdout/stderr to files that /job/{id} tails. It
shares the pod filesystem/network with the /exec shell (so e.g. PythonEnv's FIFOs
in /tmp are visible to both).

How stdout/stderr/exit_code stay clean (no PTY scraping): the user command is
written to a temp script and sourced in the shell with stdout/stderr redirected to
separate files; the exit code is written atomically (write .tmp then rename) to an
rc file. The server polls for the rc file, so it never parses a merged byte stream
and can't deadlock on pipe buffering.

Concurrency: one shell per pod, serialized by a lock (commands run one at a time).
For parallelism, lease more sessions. Run uvicorn with a single worker.
"""

import base64
import os
import signal
import subprocess
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

WORK = "/tmp/exec_server"
JOBS = "/tmp/exec_server_jobs"
os.makedirs(WORK, exist_ok=True)
os.makedirs(JOBS, exist_ok=True)

app = FastAPI()


def _read(path: str) -> str:
    try:
        with open(path, "r", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


class Shell:
    """A single persistent bash process; commands are serialized by a lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._spawn()

    def _spawn(self) -> None:
        # start_new_session=True -> own process group, so a timeout can kill the
        # whole command subtree with killpg. bash reads commands from stdin.
        self.proc = subprocess.Popen(
            ["bash"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            bufsize=0,
        )

    def _alive(self) -> bool:
        return self.proc.poll() is None

    def _kill(self) -> None:
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:
            pass

    def reset(self) -> None:
        with self._lock:
            self._kill()
            self._spawn()

    def _cleanup(self, base: str) -> None:
        for ext in (".sh", ".out", ".err", ".rc"):
            try:
                os.remove(base + ext)
            except OSError:
                pass

    def run(self, cmd: str, timeout: float) -> dict:
        with self._lock:
            if not self._alive():
                self._spawn()

            cid = uuid.uuid4().hex
            base = os.path.join(WORK, cid)
            script = base + ".sh"
            out_f, err_f, rc_f = base + ".out", base + ".err", base + ".rc"
            with open(script, "w") as f:
                f.write(cmd)

            # Run in the persistent shell so cwd/env persist. Redirect user I/O to
            # files; stdin from /dev/null so the command can't eat our control pipe.
            # Write the exit code atomically so the poller only sees a complete rc.
            control = (
                f"source {script} > {out_f} 2> {err_f} < /dev/null; "
                f'__rc=$?; printf %s "$__rc" > {rc_f}.tmp; mv {rc_f}.tmp {rc_f}\n'
            )
            start = time.monotonic()
            try:
                self.proc.stdin.write(control.encode())
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError):
                self._cleanup(base)
                self._spawn()
                return {
                    "stdout": "",
                    "stderr": "shell was dead; respawned -- retry",
                    "exit_code": None,
                    "duration_s": 0.0,
                    "timed_out": False,
                    "shell_died": True,
                }

            deadline = start + timeout
            while True:
                if os.path.exists(rc_f):
                    rc = _read(rc_f).strip()
                    out, err = _read(out_f), _read(err_f)
                    self._cleanup(base)
                    return {
                        "stdout": out,
                        "stderr": err,
                        "exit_code": int(rc) if rc.lstrip("-").isdigit() else None,
                        "duration_s": round(time.monotonic() - start, 3),
                        "timed_out": False,
                        "shell_died": False,
                    }
                if not self._alive():  # user ran `exit` or crashed the shell
                    out, err = _read(out_f), _read(err_f)
                    self._cleanup(base)
                    self._spawn()
                    return {
                        "stdout": out,
                        "stderr": err,
                        "exit_code": None,
                        "duration_s": round(time.monotonic() - start, 3),
                        "timed_out": False,
                        "shell_died": True,
                    }
                if time.monotonic() > deadline:
                    # a hung foreground command can't be interrupted cleanly ->
                    # kill the process group and respawn a fresh shell.
                    out, err = _read(out_f), _read(err_f)
                    self._kill()
                    self._cleanup(base)
                    self._spawn()
                    return {
                        "stdout": out,
                        "stderr": err,
                        "exit_code": None,
                        "duration_s": round(time.monotonic() - start, 3),
                        "timed_out": True,
                        "shell_died": True,
                    }
                time.sleep(0.01)


class _Job:
    __slots__ = ("proc", "out_path", "err_path")

    def __init__(self, proc: subprocess.Popen, out_path: str, err_path: str) -> None:
        self.proc = proc
        self.out_path = out_path
        self.err_path = err_path


class JobManager:
    """Detached background jobs. Each runs in its own process group so it neither
    blocks the persistent /exec shell nor dies with it, and can be killed as a
    subtree. stdout/stderr stream to files that /job/{id} reads on demand."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, _Job] = {}

    def start(self, cmd: str, env: dict | None, cwd: str | None) -> str:
        job_id = uuid.uuid4().hex
        out_path = os.path.join(JOBS, job_id + ".out")
        err_path = os.path.join(JOBS, job_id + ".err")
        full_env = dict(os.environ)
        if env:
            full_env.update({str(k): str(v) for k, v in env.items()})
        out_f = open(out_path, "wb")
        err_f = open(err_path, "wb")
        try:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                executable="/bin/bash",
                stdin=subprocess.DEVNULL,
                stdout=out_f,
                stderr=err_f,
                cwd=cwd or None,
                env=full_env,
                start_new_session=True,
            )
        finally:
            # The child holds its own dup'd fds; the parent's copies can be closed
            # so long-running servers don't leak an fd per job.
            out_f.close()
            err_f.close()
        with self._lock:
            self._jobs[job_id] = _Job(proc, out_path, err_path)
        return job_id

    def status(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        rc = job.proc.poll()
        return {
            "job_id": job_id,
            "completed": rc is not None,
            "exit_code": rc,
            "stdout": _read(job.out_path),
            "stderr": _read(job.err_path),
        }


shell = Shell()
jobs = JobManager()


class Cmd(BaseModel):
    cmd: str
    timeout: float = 60.0


class UploadReq(BaseModel):
    path: str
    content_b64: str


class JobReq(BaseModel):
    cmd: str
    env: dict[str, str] | None = None
    cwd: str | None = None


@app.post("/exec")
def exec_cmd(c: Cmd) -> dict:
    return shell.run(c.cmd, c.timeout)


@app.post("/reset")
def reset() -> dict:
    shell.reset()
    return {"status": "reset"}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "shell_alive": shell._alive()}


@app.post("/upload")
def upload(req: UploadReq) -> dict:
    data = base64.b64decode(req.content_b64)
    parent = os.path.dirname(req.path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(req.path, "wb") as f:
        f.write(data)
    return {"ok": True, "size": len(data)}


@app.get("/read_file")
def read_file(path: str = Query(...)) -> dict:
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"not found: {path}")
    with open(path, "rb") as f:
        data = f.read()
    return {"content_b64": base64.b64encode(data).decode(), "size": len(data)}


@app.post("/start_job")
def start_job(req: JobReq) -> dict:
    return {"job_id": jobs.start(req.cmd, req.env, req.cwd)}


@app.get("/job/{job_id}")
def job_status(job_id: str) -> dict:
    try:
        return jobs.status(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown job: {job_id}")
