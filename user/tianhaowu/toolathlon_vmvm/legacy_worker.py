from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import io
import json
import os
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXIT_FATAL = 70
EXIT_RETRYABLE = 75
RESULT_MARKER = "__TOOLATHLON_JSON__="


class ServiceHTTPError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[-2000:]}")
        self.status = status
        self.body = body


class ServiceTransportError(RuntimeError):
    pass


def _service_proxy_url() -> str | None:
    return os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY")


def _service_opener() -> urllib.request.OpenerDirector:
    proxy_url = _service_proxy_url()
    proxies = {"http": proxy_url} if proxy_url else {}
    return urllib.request.build_opener(urllib.request.ProxyHandler(proxies))


def _cache_bust(url: str) -> str:
    separator = "&" if urllib.parse.urlsplit(url).query else "?"
    return f"{url}{separator}poll={time.time_ns()}"


def _retryable_status(status: int) -> bool:
    return status in {408, 409, 425, 429} or status >= 500


def _request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    opener = _service_opener()
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        raise ServiceHTTPError(
            error.code,
            error.read().decode("utf-8", errors="replace"),
        ) from error
    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
        raise ServiceTransportError(f"{type(error).__name__}: {error}") from error
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Expected a JSON object from {url}")
    return parsed


def _emit(payload: dict[str, Any]) -> None:
    print(RESULT_MARKER + json.dumps(payload, sort_keys=True), flush=True)


def probe_model(model_base_url: str, api_key: str, model: str) -> int:
    request = urllib.request.Request(
        f"{model_base_url.rstrip('/')}/models",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        _emit({"error": f"HTTP {error.code}: {body[-2000:]}", "status": error.code, "body": body})
        return EXIT_RETRYABLE if _retryable_status(error.code) else EXIT_FATAL
    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
        _emit({"error": f"{type(error).__name__}: {error}", "type": "model_transport_error"})
        return EXIT_RETRYABLE

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        _emit({"error": f"{type(error).__name__}: {error}", "type": "invalid_model_response"})
        return EXIT_FATAL
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        _emit({"error": "Model endpoint returned an invalid models payload", "type": "invalid_model_response"})
        return EXIT_FATAL
    models = {str(item.get("id")) for item in payload["data"] if isinstance(item, dict)}
    if model not in models:
        _emit({"error": f"Endpoint does not advertise {model!r}", "models": sorted(models)})
        return EXIT_FATAL
    _emit({"model": model, "models": sorted(models)})
    return 0


def status(server_url: str) -> int:
    try:
        payload = _request_json(
            "GET",
            _cache_bust(f"{server_url.rstrip('/')}/check_server_status"),
        )
    except ServiceHTTPError as error:
        _emit({"error": str(error), "status": error.status, "body": error.body})
        return EXIT_RETRYABLE if _retryable_status(error.status) else EXIT_FATAL
    except ServiceTransportError as error:
        _emit({"error": str(error), "type": "service_transport_error"})
        return EXIT_RETRYABLE
    _emit(payload)
    return 0


def submit(server_url: str, request_path: Path) -> int:
    payload = json.loads(request_path.read_text())
    try:
        response = _request_json(
            "POST",
            f"{server_url.rstrip('/')}/submit_evaluation",
            payload=payload,
        )
    except ServiceHTTPError as error:
        _emit({"error": str(error), "status": error.status, "body": error.body})
        return EXIT_RETRYABLE if _retryable_status(error.status) else EXIT_FATAL
    except ServiceTransportError as error:
        _emit(
            {
                "error": str(error),
                "type": "submission_outcome_unknown",
            }
        )
        return EXIT_FATAL
    _emit(response)
    return 0


def monitor(
    server_url: str,
    job_id: str,
    model_base_url: str,
    ws_proxy_port: int,
    output_dir: Path,
    timeout_seconds: int,
) -> int:
    return asyncio.run(
        _monitor(
            server_url,
            job_id,
            model_base_url,
            ws_proxy_port,
            output_dir,
            timeout_seconds,
        )
    )


def _log(path: Path, message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    line = f"[{timestamp}] {message}"
    print(line, flush=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _load_downloaded(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = json.loads(path.read_text())
    if not isinstance(loaded, dict):
        raise RuntimeError(f"Malformed download record: {path}")
    return loaded


def _save_downloaded(path: Path, records: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


async def _forward_request(
    websocket: Any,
    send_lock: asyncio.Lock,
    model_base_url: str,
    api_key: str,
    request_data: dict[str, Any],
    log_path: Path,
) -> None:
    import httpx

    request_id = str(request_data["request_id"])
    endpoint = str(request_data.get("_endpoint", "/chat/completions"))
    payload = {
        key: value
        for key, value in request_data.items()
        if key not in {"request_id", "pushed", "_server_push_time"} and not key.startswith("_")
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=600, trust_env=False) as client:
            response = await client.post(
                f"{model_base_url.rstrip('/')}{endpoint}",
                json=payload,
                headers=headers,
            )
        try:
            response_body = response.json()
        except ValueError:
            response_body = {
                "error": {
                    "message": response.text[-4000:],
                    "type": "non_json_model_response",
                }
            }
        response_data = {"status_code": response.status_code, "body": response_body}
        _log(log_path, f"model response {request_id} status={response.status_code}")
    except Exception as error:
        response_data = {
            "status_code": 500,
            "body": {
                "error": {
                    "message": f"{type(error).__name__}: {error}",
                    "type": "network_error",
                    "code": "client_error",
                }
            },
        }
        _log(log_path, f"model request {request_id} failed: {type(error).__name__}: {error}")

    message = json.dumps({"type": "response", "request_id": request_id, "data": response_data})
    for attempt in range(3):
        try:
            async with send_lock:
                await websocket.send(message)
            return
        except Exception as error:
            if attempt == 2:
                raise
            _log(log_path, f"response send retry {attempt + 1}/3 for {request_id}: {error}")
            await asyncio.sleep(attempt + 1)


async def _websocket_connection(
    websocket: Any,
    model_base_url: str,
    api_key: str,
    stop: asyncio.Event,
    log_path: Path,
) -> None:
    send_lock = asyncio.Lock()
    active: set[asyncio.Task[None]] = set()

    async def heartbeat() -> None:
        while not stop.is_set():
            await asyncio.sleep(30)
            async with send_lock:
                await websocket.send(json.dumps({"type": "heartbeat"}))

    heartbeat_task = asyncio.create_task(heartbeat())

    def finish_request(task: asyncio.Task[None]) -> None:
        active.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            _log(log_path, f"request task failed: {type(error).__name__}: {error}")

    try:
        async for raw in websocket:
            data = json.loads(raw)
            message_type = data.get("type")
            if message_type == "new_requests":
                for request_data in data.get("requests") or []:
                    task = asyncio.create_task(
                        _forward_request(
                            websocket,
                            send_lock,
                            model_base_url,
                            api_key,
                            request_data,
                            log_path,
                        )
                    )
                    active.add(task)
                    task.add_done_callback(finish_request)
            elif message_type == "error":
                raise RuntimeError(f"Toolathlon WebSocket error: {data.get('message')}")
            if stop.is_set():
                break
    finally:
        heartbeat_task.cancel()
        pending = list(active)
        for task in pending:
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


async def _websocket_loop(
    ws_url: str,
    model_base_url: str,
    api_key: str,
    stop: asyncio.Event,
    log_path: Path,
) -> None:
    from websockets import connect

    delay = 5
    proxy_url = _service_proxy_url()
    while not stop.is_set():
        try:
            _log(log_path, f"connecting websocket {ws_url}")
            async with connect(
                ws_url,
                proxy=proxy_url,
                ping_interval=20,
                ping_timeout=120,
                max_size=32 * 1024 * 1024,
            ) as websocket:
                delay = 5
                _log(log_path, "websocket connected")
                await _websocket_connection(
                    websocket,
                    model_base_url,
                    api_key,
                    stop,
                    log_path,
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if stop.is_set():
                return
            _log(log_path, f"websocket reconnect in {delay}s: {type(error).__name__}: {error}")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)


async def _download_task(
    client: Any,
    server_url: str,
    job_id: str,
    task_name: str,
    output_dir: Path,
    records: dict[str, Any],
) -> None:
    response = await client.get(
        f"{server_url}/get_task_archive",
        params={"job_id": job_id, "task_name": task_name},
    )
    response.raise_for_status()
    expected_md5 = response.headers.get("X-Content-MD5")
    actual_md5 = hashlib.md5(response.content).hexdigest()
    if expected_md5 and expected_md5 != actual_md5:
        raise RuntimeError(f"Archive checksum mismatch for {task_name}: {actual_md5} != {expected_md5}")
    finalpool = output_dir / "finalpool"
    finalpool.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as archive:
        archive.extractall(finalpool, filter="data")
    records[task_name] = {"md5": actual_md5, "downloaded_at": time.time()}
    _save_downloaded(output_dir / ".downloaded_tasks.json", records)


async def _download_completed(
    client: Any,
    server_url: str,
    job_id: str,
    output_dir: Path,
    records: dict[str, Any],
) -> None:
    response = await client.get(
        f"{server_url}/get_completed_tasks",
        params={"job_id": job_id, "poll": time.time_ns()},
    )
    response.raise_for_status()
    for task_name in response.json().get("task_names") or []:
        if task_name not in records:
            await _download_task(client, server_url, job_id, task_name, output_dir, records)


async def _download_static(
    client: Any,
    server_url: str,
    job_id: str,
    output_dir: Path,
) -> None:
    response = await client.get(
        f"{server_url}/get_static_files",
        params={"job_id": job_id},
    )
    response.raise_for_status()
    files = response.json()
    if not isinstance(files, dict):
        raise RuntimeError("Malformed static-file response")
    for name, content in files.items():
        if content is None:
            continue
        path = output_dir / str(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content))


async def _monitor(
    server_url: str,
    job_id: str,
    model_base_url: str,
    ws_proxy_port: int,
    output_dir: Path,
    timeout_seconds: int,
) -> int:
    import httpx

    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "client.log"
    websocket_log = output_dir / "ws_client.log"
    records = _load_downloaded(output_dir / ".downloaded_tasks.json")
    api_key = os.environ.get("TOOLATHLON_OPENAI_API_KEY", "")
    parsed = urllib.parse.urlparse(server_url)
    ws_url = f"ws://{parsed.hostname}:{ws_proxy_port}/ws?job_id={job_id}"
    stop = asyncio.Event()
    websocket_task = asyncio.create_task(_websocket_loop(ws_url, model_base_url, api_key, stop, websocket_log))
    started = time.monotonic()
    log_offset = 0
    try:
        async with httpx.AsyncClient(
            timeout=120,
            proxy=_service_proxy_url(),
            trust_env=False,
        ) as client:
            while time.monotonic() - started <= timeout_seconds:
                try:
                    log_response = await client.get(
                        f"{server_url}/get_server_log",
                        params={
                            "job_id": job_id,
                            "offset": log_offset,
                            "poll": time.time_ns(),
                        },
                    )
                    log_response.raise_for_status()
                    log_data = log_response.json()
                    if content := log_data.get("content"):
                        with (output_dir / "server.log").open("a", encoding="utf-8") as handle:
                            handle.write(str(content))
                    log_offset = int(log_data.get("offset", log_offset))
                    await _download_completed(client, server_url, job_id, output_dir, records)
                    status_response = await client.get(
                        f"{server_url}/poll_job_status",
                        params={"job_id": job_id, "poll": time.time_ns()},
                    )
                    status_response.raise_for_status()
                    status_data = status_response.json()
                    status_value = str(status_data.get("status", ""))
                    _log(log_path, f"job status={status_value} downloaded={len(records)}")
                    if status_value == "completed":
                        await _download_completed(client, server_url, job_id, output_dir, records)
                        await _download_static(client, server_url, job_id, output_dir)
                        return 0
                    if status_value in {"failed", "timeout", "cancelled"}:
                        _emit(status_data)
                        return EXIT_FATAL
                except (httpx.HTTPError, json.JSONDecodeError, ValueError) as error:
                    _log(log_path, f"status/download retry: {type(error).__name__}: {error}")
                await asyncio.sleep(5)
            await client.post(f"{server_url}/cancel_job", params={"job_id": job_id})
        _emit({"error": "evaluation timeout", "job_id": job_id})
        return EXIT_FATAL
    finally:
        stop.set()
        websocket_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await websocket_task


def pack(output_dir: Path, archive: Path) -> int:
    names = {
        ".downloaded_tasks.json",
        "client.log",
        "eval_res_all.jsonl",
        "eval_stats.json",
        "server.log",
        "traj_log_all.jsonl",
        "ws_client.log",
    }
    files = [path for path in output_dir.iterdir() if path.is_file() and path.name in names]
    finalpool = output_dir / "finalpool"
    if finalpool.exists():
        for name in ("eval_res.json", "status.json", "traj_log.json"):
            files.extend(finalpool.glob(f"*/{name}"))
    with tarfile.open(archive, "w:gz") as handle:
        for path in sorted(files):
            handle.add(path, arcname=path.relative_to(output_dir))
    _emit({"archive": str(archive), "files": len(files), "size": archive.stat().st_size})
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--server-url", required=True)

    probe_parser = subparsers.add_parser("probe-model")
    probe_parser.add_argument("--model-base-url", required=True)
    probe_parser.add_argument("--api-key", required=True)
    probe_parser.add_argument("--model", required=True)

    submit_parser = subparsers.add_parser("submit")
    submit_parser.add_argument("--server-url", required=True)
    submit_parser.add_argument("--request", type=Path, required=True)

    monitor_parser = subparsers.add_parser("monitor")
    monitor_parser.add_argument("--server-url", required=True)
    monitor_parser.add_argument("--job-id", required=True)
    monitor_parser.add_argument("--model-base-url", required=True)
    monitor_parser.add_argument("--ws-proxy-port", type=int, required=True)
    monitor_parser.add_argument("--output-dir", type=Path, required=True)
    monitor_parser.add_argument("--timeout-seconds", type=int, required=True)

    pack_parser = subparsers.add_parser("pack")
    pack_parser.add_argument("--output-dir", type=Path, required=True)
    pack_parser.add_argument("--archive", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status":
        return status(args.server_url)
    if args.command == "probe-model":
        return probe_model(args.model_base_url, args.api_key, args.model)
    if args.command == "submit":
        return submit(args.server_url, args.request)
    if args.command == "monitor":
        return monitor(
            args.server_url,
            args.job_id,
            args.model_base_url,
            args.ws_proxy_port,
            args.output_dir,
            args.timeout_seconds,
        )
    return pack(args.output_dir, args.archive)


if __name__ == "__main__":
    raise SystemExit(main())
