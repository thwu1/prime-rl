"""
Algebraic Effect Handlers for Python — Replay-based Implementation

Uses the 'replay' technique for implementing delimited continuations:
when an effect is performed, a BaseException is raised and caught by
the enclosing handler. To resume, the body is re-executed from scratch
with previously handled effects replayed from a log. Multi-shot
continuations are supported by snapshotting the log before each resume.

Each handler's log records ALL values returned to perform() calls in
its body — both for effects it handles (via resume) and for effects it
forwards to outer handlers (by recording the returned value). This
ensures that inner handler re-runs do not re-trigger forwarded effects
at the outer level.

Handler scoping is managed via thread-local storage holding a chain
of perform functions, each forwarding unhandled effects to its
predecessor.
"""

import threading

_tls = threading.local()


class Effect:
    """
    Declares a new effect type.

    Each Effect instance is unique by object identity — two Effects
    with the same name are still distinct effects.
    """

    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return f"Effect({self.name!r})"


class _EffectOp(BaseException):
    """Internal signal for an unhandled effect operation.

    Inherits from BaseException (not Exception) so that user code
    with ``except Exception`` blocks cannot accidentally intercept it.
    """
    __slots__ = ('effect', 'arg', 'token')

    def __init__(self, effect, arg, token):
        self.effect = effect
        self.arg = arg
        self.token = token


def perform(effect, arg=None):
    """Perform an effect operation.

    Transfers control to the nearest enclosing handler for *effect*.
    Returns whatever value the handler passes to ``resume()``.
    Raises ``RuntimeError`` if no handler is in scope.
    """
    fn = getattr(_tls, '_pfn', None)
    if fn is None:
        raise RuntimeError(f"Unhandled effect: {effect}")
    return fn(effect, arg)


def handle(body_fn, handlers):
    """Run *body_fn()* with effect *handlers* installed.

    *handlers* maps ``Effect`` instances to handler functions with
    signature ``(arg, resume) -> result``.

    The log records values returned to perform() for ALL effects
    encountered during body execution — both handled (via resume)
    and forwarded (result from outer handler). During replay, the
    log provides values for both kinds, preventing re-forwarding.
    """
    token = object()
    log = []

    def _run():
        """Execute body_fn with our perform function installed."""
        idx = [0]
        prev = getattr(_tls, '_pfn', None)

        def _pfn(eff, arg):
            if idx[0] < len(log):
                # Replay: return previously recorded value
                val = log[idx[0]]
                idx[0] += 1
                return val

            # New effect (not in replay log)
            if eff in handlers:
                # We handle this effect — signal to our _loop
                raise _EffectOp(eff, arg, token)

            # Not our effect — forward to enclosing handler
            if prev is None:
                raise RuntimeError(f"Unhandled effect: {eff}")
            # If prev returns, record the result for future replays.
            # If prev raises _EffectOp, the exception propagates
            # without recording (we'll be re-created on outer resume).
            result = prev(eff, arg)
            log.append(result)
            idx[0] += 1
            return result

        _tls._pfn = _pfn
        try:
            return body_fn()
        finally:
            _tls._pfn = prev

    def _loop():
        """Run-catch-resume loop."""
        try:
            return _run()
        except _EffectOp as op:
            if op.token is not token:
                raise
            # Snapshot for multi-shot support
            snap = list(log)

            def resume(value):
                log.clear()
                log.extend(snap)
                log.append(value)
                return _loop()

            return handlers[op.effect](op.arg, resume)

    return _loop()
