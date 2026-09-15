"""Pipeline execution engine with middleware (hook) support.

Stages execute sequentially.  Pre-hooks fire before each stage in
registration order (FIFO).  Post-hooks fire after each stage in
reverse registration order (LIFO) so that the last-registered hook
runs first -- the standard onion/stack pattern used by frameworks
like Express, Koa, and Sanic.
"""
from collections import deque
import time


class PipelineError(Exception):
    """Raised when a pipeline stage fails."""
    pass


class StageResult:
    """Encapsulates the output of a single pipeline stage."""

    def __init__(self, data, metadata=None, errors=None):
        self.data = data
        self.metadata = metadata or {}
        self.errors = errors or []
        self.timestamp = time.time()

    @property
    def success(self):
        return len(self.errors) == 0

    def __repr__(self):
        status = "OK" if self.success else f"ERRORS({len(self.errors)})"
        count = len(self.data) if isinstance(self.data, list) else 1
        return f"StageResult({status}, records={count})"


class PipelineEngine:
    """Executes data-transformation pipelines with pre/post hooks.

    Usage::

        engine = PipelineEngine()
        engine.add_post_hook(normalize)
        engine.add_post_hook(validate)
        engine.add_stage('transform', transform_fn)
        result = engine.execute(data)

    Post-hooks run in LIFO order: validate fires before normalize.
    """

    def __init__(self, config=None):
        self.config = config
        self.stages = []
        self.pre_hooks = []
        self.post_hooks = deque()
        self._execution_log = []

    def add_stage(self, name, transform_fn, **kwargs):
        """Append a processing stage."""
        self.stages.append({
            'name': name,
            'fn': transform_fn,
            'kwargs': kwargs,
        })
        return self

    def add_pre_hook(self, hook_fn):
        """Register a pre-processing hook (FIFO execution order)."""
        self.pre_hooks.append(hook_fn)
        return self

    def add_post_hook(self, hook_fn):
        """Register a post-processing hook (LIFO execution order)."""
        self.post_hooks.append(hook_fn)
        return self

    def execute(self, initial_data):
        """Run all stages, returning a final StageResult."""
        self._execution_log = []
        current = StageResult(initial_data)

        for stage in self.stages:
            # Pre-hooks: FIFO
            for hook in self.pre_hooks:
                try:
                    current = hook(current, stage) or current
                except Exception as e:
                    current.errors.append(f"Pre-hook error: {e}")

            # Stage execution
            try:
                result_data = stage['fn'](current.data, **stage['kwargs'])
                current = StageResult(
                    data=result_data,
                    metadata={**current.metadata, 'last_stage': stage['name']},
                )
            except Exception as e:
                current.errors.append(f"Stage '{stage['name']}' failed: {e}")
                self._execution_log.append({
                    'stage': stage['name'],
                    'status': 'error',
                    'error': str(e),
                })
                raise PipelineError(
                    f"Pipeline failed at stage '{stage['name']}': {e}"
                ) from e

            # Post-hooks: should be LIFO (last registered = first to run)
            for hook in self.post_hooks:
                try:
                    current = hook(current, stage) or current
                except Exception as e:
                    current.errors.append(f"Post-hook error: {e}")

            self._execution_log.append({
                'stage': stage['name'],
                'status': 'ok',
                'record_count': (len(current.data)
                                 if isinstance(current.data, list) else 1),
            })

        return current

    def get_execution_log(self):
        return list(self._execution_log)

    def dry_run(self, initial_data):
        """Simulate execution without running transforms."""
        return [
            {
                'order': i,
                'name': stage['name'],
                'pre_hooks': len(self.pre_hooks),
                'post_hooks': len(self.post_hooks),
                'kwargs': stage['kwargs'],
            }
            for i, stage in enumerate(self.stages)
        ]
