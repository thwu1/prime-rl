"""
Tests for the ELF JIT Loader.
Verifies correct ELF parsing, symbol resolution, relocation application,
and function execution across multiple incrementally compiled object files.
"""

import sys
import pytest

sys.path.insert(0, "/app")
from jit_loader import JITLoader

CELL1 = "/app/objects/cell1.o"
CELL2 = "/app/objects/cell2.o"
CELL3 = "/app/objects/cell3.o"
CELL4 = "/app/objects/cell4.o"


@pytest.fixture
def loader_all():
    """Load all four cells in dependency order."""
    loader = JITLoader()
    loader.load(CELL1, CELL2, CELL3, CELL4)
    return loader


@pytest.fixture
def loader_partial():
    """Load only cells 1 and 2."""
    loader = JITLoader()
    loader.load(CELL1, CELL2)
    return loader


def test_add_basic(loader_all):
    assert loader_all.call("add", 10, 20) == 30


def test_add_negative(loader_all):
    assert loader_all.call("add", -5, 3) == -2


def test_multiply_basic(loader_all):
    assert loader_all.call("multiply", 5, 7) == 35


def test_get_shared(loader_all):
    """get_shared reads a static int initialized to 42 from .data section."""
    assert loader_all.call("get_shared") == 42


def test_compute_sum(loader_all):
    """compute_sum() = add(get_shared(), 8) = add(42, 8) = 50"""
    assert loader_all.call("compute_sum") == 50


def test_compute_product(loader_all):
    """compute_product() = multiply(get_shared(), 3) = multiply(42, 3) = 126"""
    assert loader_all.call("compute_product") == 126


def test_final_result(loader_all):
    """final_result() = add(compute_sum(), compute_product()) = add(50, 126) = 176"""
    assert loader_all.call("final_result") == 176


def test_poly_eval(loader_all):
    """poly_eval() = quadratic(2,3,5,4) = 2*16 + 3*4 + 5 = 49"""
    assert loader_all.call("poly_eval") == 49


def test_quadratic_direct(loader_all):
    """quadratic(1,0,0,5) = 1*25 + 0 + 0 = 25"""
    assert loader_all.call("quadratic", 1, 0, 0, 5) == 25


def test_quadratic_linear(loader_all):
    """quadratic(0,1,0,7) = 0 + 7 + 0 = 7"""
    assert loader_all.call("quadratic", 0, 1, 0, 7) == 7


def test_bss_initial_zero(loader_all):
    """BSS-resident counter must start at 0."""
    assert loader_all.call("get_counter") == 0


def test_increment_stateful(loader_all):
    """increment() modifies BSS counter; successive calls accumulate."""
    assert loader_all.call("increment") == 1
    assert loader_all.call("increment") == 2
    assert loader_all.call("get_counter") == 2


def test_partial_load(loader_partial):
    """Loading only cell1+cell2 should resolve all cell2 dependencies."""
    assert loader_partial.call("compute_sum") == 50
    assert loader_partial.call("add", 100, 200) == 300


def test_independent_instances():
    """Separate JITLoader instances must have fully independent memory."""
    l1 = JITLoader()
    l1.load(CELL1, CELL4)
    l2 = JITLoader()
    l2.load(CELL1, CELL4)

    l1.call("increment")
    l1.call("increment")
    assert l1.call("get_counter") == 2
    assert l2.call("get_counter") == 0
