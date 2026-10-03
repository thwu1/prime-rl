"""Sandoq sandbox provider — the reusable sandbox backend for prime-rl recipes.

``install()`` (guarded by ``VF_SANDBOX_PROVIDER``) rebinds the ``prime_sandboxes``
symbols that vendored ``verifiers`` uses so all sandbox execution goes to Meta's sandoq
service instead of Prime Intellect's — without editing verifiers or prime-rl. It is invoked
automatically by the sibling ``sitecustomize.py`` at interpreter startup (so it runs in every
env-server worker, the trainer, and inference). It covers both families:

- **v0** (``SandboxEnv``/``SandboxMixin``): async exec funnels through
  ``verifiers.utils.threaded_sandbox_client.AsyncSandboxClient`` (a module-global bound at
  import) + sync teardown ``SandboxClient(APIClient())`` in two sites — patched directly.
- **v1** (``verifiers/v1/runtimes/prime.py``, ``runtime.type = "prime"``): imports
  ``AsyncSandboxClient``/``SandboxClient``/``APIClient`` from ``prime_sandboxes``
  *function-locally*, so patching the ``prime_sandboxes`` source module redirects it at
  call time.

Each patch is best-effort (try/except) so verifiers version differences never abort install.
Agent-inside recipes can use :class:`sandoq_provider.tunnel.SandoqRelayTunnel`
after the runtime starts: it binds a session's named ``tunnel`` port back to the
caller's interception server. The recipe owns that lifecycle because the Sandoq
session URL does not exist until the runtime has been leased.
"""

from __future__ import annotations

import logging
import os
import signal

__all__ = ["install", "is_active"]

_installed = False
logger = logging.getLogger(__name__)


def _provider_auth_is_external() -> None:
    """The selected Sandoq provider authenticates through its own token file."""


def is_active() -> bool:
    return os.environ.get("VF_SANDBOX_PROVIDER", "").strip().lower() in {"sandoq", "oci-runner"}


def install() -> bool:
    """Patch verifiers + prime_sandboxes to use the selected provider. Idempotent; no-op
    unless ``VF_SANDBOX_PROVIDER`` is ``sandoq`` or ``oci-runner``.
    """
    global _installed
    if not is_active():
        return False
    if _installed:
        return True

    import importlib

    from sandoq_provider import client, sync_client

    provider = os.environ.get("VF_SANDBOX_PROVIDER", "").strip().lower()
    async_client = client.SandoqAsyncSandboxClient
    oci_client = None
    if provider == "oci-runner":
        from sandoq_provider import oci_client as selected_oci_client

        oci_client = selected_oci_client
        async_client = selected_oci_client.OCIRunnerAsyncSandboxClient

    applied: list[str] = []

    def _patch(module_path: str, attr: str, value: object) -> None:
        # Best-effort: a missing module/attr (verifiers version differences) must not abort.
        try:
            module = importlib.import_module(module_path)
            setattr(module, attr, value)
            applied.append(f"{module_path}.{attr}")
        except Exception as e:  # noqa: BLE001
            logger.debug("sandoq shim: skipped %s.%s (%s)", module_path, attr, e)

    # (A) prime_sandboxes source module — covers the v1 `prime` runtime
    # (verifiers/v1/runtimes/prime.py imports these function-locally, resolving them at
    # call time) plus any other direct importer.
    _patch("prime_sandboxes", "AsyncSandboxClient", async_client)
    _patch("prime_sandboxes", "SandboxClient", sync_client.SandoqSandboxClient)
    _patch("prime_sandboxes.core", "APIClient", sync_client.SandoqAPIClient)
    # Verifiers 0.9 added a Prime-platform credential check to PrimeRuntime's
    # constructor. The runtime class is retained as the protocol adapter, but
    # its clients above are Sandoq clients and authenticate with OCI_RUNNER_TOKEN_FILE.
    _patch("verifiers.v1.utils.prime", "ensure_prime_auth", _provider_auth_is_external)
    _patch("verifiers.v1.runtimes.prime", "ensure_prime_auth", _provider_auth_is_external)

    # (B) v0 seams — module-globals bound at import time, so patch them directly.
    # ThreadedAsyncSandboxClient reads tsc.AsyncSandboxClient per-thread at call time
    # (covers SandboxEnv, SandboxMixin, and v1 create_sandbox_lease async exec); the two
    # sync teardown sites construct SandboxClient(APIClient()).
    _patch(
        "verifiers.utils.threaded_sandbox_client",
        "AsyncSandboxClient",
        async_client,
    )
    if provider == "oci-runner":
        # Running OCI behind ThreadedAsyncSandboxClient makes cancellation stop
        # at the executor Future while image bootstrap continues in its worker
        # thread, which can strand a pre-readiness lease during SIGTERM teardown.
        _patch(
            "verifiers.utils.threaded_sandbox_client",
            "ThreadedAsyncSandboxClient",
            async_client,
        )
    for module_path in (
        "verifiers.envs.sandbox_env",
        "verifiers.envs.experimental.sandbox_mixin",
    ):
        if provider == "oci-runner":
            _patch(module_path, "ThreadedAsyncSandboxClient", async_client)
        _patch(module_path, "SandboxClient", sync_client.SandoqSandboxClient)
        _patch(module_path, "APIClient", sync_client.SandoqAPIClient)

    if oci_client is not None:
        try:
            environment_module = importlib.import_module("verifiers.envs.environment")
            environment_class = environment_module.Environment
            original_post_init = environment_class.__post_init__
            if not getattr(original_post_init, "_oci_signal_cleanup", False):

                def _oci_post_init(self: object) -> None:
                    original_post_init(self)
                    previous_handler = signal.getsignal(signal.SIGTERM)

                    def _oci_sigterm(sig: int, frame: object) -> object:
                        cleanup = oci_client.delete_registered_sessions_sync()
                        if cleanup["failed"]:
                            logger.error("OCI runner signal cleanup failed: %s", cleanup["failed"])
                        if callable(previous_handler):
                            return previous_handler(sig, frame)
                        raise SystemExit(143)

                    _oci_sigterm._oci_session_cleanup = True  # type: ignore[attr-defined]
                    signal.signal(signal.SIGTERM, _oci_sigterm)

                _oci_post_init._oci_signal_cleanup = True  # type: ignore[attr-defined]
                environment_class.__post_init__ = _oci_post_init
                applied.append("verifiers.envs.environment.Environment.__post_init__")
        except Exception as e:  # noqa: BLE001
            logger.debug("sandoq shim: skipped OCI signal cleanup (%s)", e)

    _installed = True
    logger.info(
        "sandbox provider installed (VF_SANDBOX_PROVIDER=%s); patched: %s",
        provider,
        ", ".join(applied),
    )
    return True
