"""
Python ctypes bindings for libterminal.so -- VT/ANSI Terminal State Machine

Complete this module so that:
  1. It loads /app/libterminal.so via ctypes.CDLL
  2. Defines a CellStruct (ctypes.Structure) whose memory layout matches
     the C Cell typedef in terminal.h exactly (mind alignment/padding)
  3. Sets argtypes and restype for every exported API function:
       terminal_create, terminal_destroy, terminal_process,
       terminal_get_cell, terminal_get_cursor_x, terminal_get_cursor_y
  4. Provides a TerminalEmulator class with the interface below

Save the completed file as /app/bindings.py
"""
import ctypes
import json

# TODO: Define CellStruct(ctypes.Structure) matching the C Cell typedef.
#       Pay attention to field types and natural alignment/padding.

# TODO: Load /app/libterminal.so via ctypes.CDLL

# TODO: Set argtypes and restype for all six API functions.
#       terminal_get_cell returns a Cell struct by value.


class TerminalEmulator:
    """High-level wrapper around the C terminal shared library."""

    def __init__(self, width: int, height: int):
        """Create a terminal of the given dimensions via terminal_create."""
        self.width = width
        self.height = height
        # TODO: call terminal_create, store the opaque handle

    def process(self, data: bytes):
        """Feed raw bytes into the terminal state machine via terminal_process."""
        # TODO: convert data to ctypes array, call terminal_process
        pass

    def get_cell(self, x: int, y: int) -> dict:
        """Return cell state as dict with keys: cp, fg (list), bg (list), at."""
        # TODO: call terminal_get_cell, unpack CellStruct into dict
        pass

    def cursor(self) -> tuple:
        """Return (x, y) cursor position."""
        # TODO: call terminal_get_cursor_x and terminal_get_cursor_y
        pass

    def get_state(self) -> dict:
        """
        Return the full terminal state as a dict identical in structure to
        the JSON that vtterm writes to stdout:
        {
          "cursor": {"x": ..., "y": ...},
          "width": ..., "height": ...,
          "cells": [[{"cp": ..., "fg": [r,g,b], "bg": [r,g,b], "at": ...}, ...], ...]
        }
        """
        # TODO: iterate all cells and build the dict
        pass

    def close(self):
        """Destroy the terminal via terminal_destroy."""
        # TODO: call terminal_destroy, clear handle
        pass
