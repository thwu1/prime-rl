"""Auto-activate the sandoq sandbox backend at interpreter startup.

A recipe opts into the sandoq extension by putting this directory on ``PYTHONPATH``
(see ``enable.sh`` / ``README.md``). Python's ``site`` machinery imports this module
at startup in **every** process that runs on the recipe's prime-rl runtime — the
env-server broker, each spawned env-server worker, the trainer, and inference — so
the provider is installed everywhere it's needed with **no edits to prime-rl or
verifiers**.

No-op unless ``VF_SANDBOX_PROVIDER`` selects ``sandoq`` or ``oci-runner``. Lazy: rather than importing the heavy
``verifiers``/``prime_sandboxes`` stack at startup (which would slow every process and
risk import-order issues in vLLM/torch), we install a one-shot meta-path hook that
runs ``sandoq_provider.install()`` the moment the app first imports one of the sandbox
client seams — so processes that never touch sandboxes pay nothing. Never raises (a
startup hook must not break the interpreter).
"""

import os

if os.environ.get("VF_SANDBOX_PROVIDER", "").strip().lower() in {"sandoq", "oci-runner"}:
    import importlib.abc
    import importlib.util
    import sys

    # First import of any of these means the app is about to use a sandbox client.
    # Hook the completed v1 runtime module rather than ``prime_sandboxes`` itself:
    # Prime-RL 0.9 performs its provider-specific auth check in PrimeRuntime.__init__,
    # and that imported alias can only be replaced after the module finishes loading.
    _TRIGGERS = frozenset(
        {
            "verifiers.v1.runtimes.prime",
            "verifiers.utils.threaded_sandbox_client",
            "verifiers.envs.sandbox_env",
            "verifiers.envs.experimental.sandbox_mixin",
        }
    )

    class _SandoqInstaller(importlib.abc.MetaPathFinder):
        """One-shot finder: on the first trigger import, wrap its loader so that
        ``install()`` runs right AFTER the module finishes loading (patching every
        seam cleanly), then get out of the import machinery's way."""

        _fired = False

        def find_spec(self, fullname, path=None, target=None):
            if _SandoqInstaller._fired or fullname not in _TRIGGERS:
                return None
            _SandoqInstaller._fired = True
            # Step aside so find_spec below doesn't recurse into us.
            try:
                sys.meta_path.remove(self)
            except ValueError:
                pass
            spec = importlib.util.find_spec(fullname)
            if spec is None or spec.loader is None:
                return None
            real_exec = spec.loader.exec_module

            def exec_module(module, _real_exec=real_exec):
                _real_exec(module)  # finish importing the trigger module first
                provider_import_in_progress = any(
                    (name == "sandoq_provider" or name.startswith("sandoq_provider."))
                    and bool(
                        getattr(
                            getattr(loaded_module, "__spec__", None),
                            "_initializing",
                            False,
                        )
                    )
                    for name, loaded_module in tuple(sys.modules.items())
                )
                provider_client = sys.modules.get("sandoq_provider.client")
                if provider_import_in_progress or (
                    provider_client is not None and not hasattr(provider_client, "SandoqAsyncSandboxClient")
                ):
                    # The pool broker imports our shared HTTP helper, which itself
                    # imports prime_sandboxes. ECR resolution can reach the same
                    # trigger while sandoq_provider.ecr is only partially built.
                    # Defer installation until a later verifiers trigger instead
                    # of importing oci_client through any half-built provider module.
                    _SandoqInstaller._fired = False
                    sys.meta_path.insert(0, self)
                    return
                try:
                    from sandoq_provider import install

                    install()
                except Exception:
                    import logging

                    logging.getLogger("sandoq_provider").warning(
                        "sandoq sitecustomize: provider install failed", exc_info=True
                    )

            spec.loader.exec_module = exec_module  # type: ignore[method-assign]
            return spec

    sys.meta_path.insert(0, _SandoqInstaller())
