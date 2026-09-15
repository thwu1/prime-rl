"""
Patch Testing Helper

Provides utilities for applying and testing patches against
the CallStateMachine implementation.

Usage:
    from patches.apply_patch import apply_patch, reset_state_machine

    # Apply a patch
    cls = apply_patch('patch_a')

    # Test with the patched class (scenario.py reimports automatically)
    from scenario import CallScenario
    s = CallScenario()

    # Reset to original
    reset_state_machine()
"""
import sys
import importlib


def apply_patch(patch_name):
    """
    Apply a named patch to CallStateMachine.

    Args:
        patch_name: One of 'patch_a' through 'patch_e'

    Returns:
        The patched CallStateMachine class
    """
    reset_state_machine()

    from state_machine import CallStateMachine
    patch_mod = importlib.import_module(f'patches.{patch_name}')
    patch_mod.apply(CallStateMachine)

    return CallStateMachine


def reset_state_machine():
    """Reset CallStateMachine to its original unpatched state."""
    mods_to_remove = [m for m in list(sys.modules.keys()) if m in (
        'state_machine', 'scenario', 'media_engine', 'signaling_bus',
    )]
    for m in mods_to_remove:
        del sys.modules[m]
