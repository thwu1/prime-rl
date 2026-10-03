"""Synchronous Prime-compatible facade used only for teardown (bulk delete).

verifiers' teardown paths construct ``SandboxClient(APIClient())`` and call
``bulk_delete(sandbox_ids=...)`` from a signal/interpreter-shutdown context.
``install()`` rebinds those module globals to these classes. Lifecycle traffic is
still owned by the process-scoped official client and its dedicated loop.
"""

from __future__ import annotations

from sandoq_provider import registry
from sandoq_provider.config import get_config
from sandoq_provider.gateway import get_gateway_adapter


class SandoqAPIClient:
    """Placeholder for ``prime_sandboxes.core.APIClient`` (constructed as ``APIClient()``)."""

    def __init__(self, *args, **kwargs) -> None:
        pass


class SandoqSandboxClient:
    """Minimal sync client: only ``delete``/``bulk_delete`` are used at teardown."""

    def __init__(self, api_client: object | None = None, *args, **kwargs) -> None:
        self._cfg = get_config()
        self._base = self._cfg.base_url

    def delete(self, sandbox_id: str, timeout: float = 30.0) -> dict:
        info = registry.get(sandbox_id)
        base_url = info.outer_base_url if info and info.outer_base_url else self._base
        deletion = get_gateway_adapter(base_url, self._cfg.owner).delete_session(
            sandbox_id,
            timeout=timeout,
        )
        registry.unregister(sandbox_id)
        return {
            "status": "deleted",
            "sandbox_id": sandbox_id,
            "verified_http_status": deletion.verified_http_status,
        }

    def bulk_delete(self, sandbox_ids=None, **kwargs) -> dict:
        ids = list(sandbox_ids or [])
        succeeded: list[str] = []
        failed: list[str] = []
        for sid in ids:
            try:
                self.delete(sid)
                succeeded.append(sid)
            except Exception:
                failed.append(sid)
        return {"succeeded": succeeded, "failed": failed, "total": len(ids)}
