"""
Algebraic Effect Handlers for Python

This module provides a runtime for algebraic effects and handlers.
Implement the core operations to make the test suite pass.

Concepts
--------
An *effect* is a typed capability that code can invoke. Effects are declared
with ``Effect(name)`` and invoked with ``perform(effect, arg)``.

A *handler* intercepts effect operations and decides how to respond. Handlers
are installed with ``handle(body_fn, handlers_dict)``. Each handler function
receives ``(arg, resume)`` where:

- ``arg``: the argument passed to ``perform()``
- ``resume``: a function that continues the computation from where
  ``perform()`` was called, with ``perform()`` returning the value passed
  to ``resume()``. ``resume()`` itself returns whatever the body eventually
  produces.

If the handler does NOT call ``resume``, the handled computation is abandoned
and ``handle()`` returns the handler's return value.

Handler scoping
---------------
- Handlers only intercept effects performed within their ``body_fn``
- Inner handlers shadow outer handlers for the same effect
- Effects not handled by the current handler propagate to outer handlers
- A handler function can itself perform effects; these propagate to handlers
  ABOVE the current handler (not to the current handler itself)

Multi-shot continuations
------------------------
The ``resume`` function may be called zero, one, or multiple times.
Multiple calls to ``resume`` with different values produce independent
continuations of the computation.
"""


class Effect:
    """
    Declares a new effect type.

    Each ``Effect`` instance is unique by object identity — two Effects
    with the same name are still distinct effects.

    Usage::

        MyEffect = Effect("MyEffect")
    """

    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return f"Effect({self.name!r})"


def perform(effect: "Effect", arg=None):
    """
    Perform an effect operation.

    Transfers control to the nearest enclosing handler for ``effect``.
    Returns whatever value the handler passes to ``resume()``.

    Raises ``RuntimeError`` if no handler for the effect is installed.

    Parameters
    ----------
    effect : Effect
        The effect to perform.
    arg : any, optional
        An argument to pass to the handler (default: ``None``).

    Returns
    -------
    any
        The value passed to ``resume()`` by the handler.
    """
    raise NotImplementedError("TODO: implement perform()")


def handle(body_fn, handlers: dict):
    """
    Run ``body_fn()`` with the given effect handlers installed.

    Parameters
    ----------
    body_fn : callable
        A zero-argument callable whose execution may perform effects.
    handlers : dict
        Maps ``Effect`` instances to handler functions.
        Each handler function has signature ``(arg, resume) -> result``:

        - ``arg``: the value passed to ``perform()``
        - ``resume``: a callable; ``resume(v)`` makes ``perform()`` return
          ``v`` in the body, and ``resume()`` itself returns the body's
          eventual result.

    Returns
    -------
    any
        Either the return value of ``body_fn()`` (if it completes without
        unhandled effects), or the return value of a handler function
        (if the handler doesn't call ``resume``).
    """
    raise NotImplementedError("TODO: implement handle()")
