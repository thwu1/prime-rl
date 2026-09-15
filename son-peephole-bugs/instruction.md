The directory `/app/son_ir/` contains a Sea of Nodes intermediate representation framework for integer expressions:

- `nodes.py` — Node type definitions and data types (i1, i8, i16, i32, i64)
- `graph.py` — Builder API for constructing IR expression DAGs
- `evaluator.py` — Reference interpreter that evaluates IR graphs with concrete inputs

Study these files to understand the IR's node types, data flow semantics, and edge-case handling (signed vs unsigned operations, overflow wrapping, type-width masking, shift-by-width behavior, division by zero).

Create `/app/son_ir/jit.py` exporting a function:

```python
def jit_compile(root_node, num_params) -> callable
```

This function must compile the IR expression DAG rooted at `root_node` into executable native machine code for the host architecture. The returned callable must:

- Accept `num_params` integer arguments (each up to 64 bits wide, maximum 6 parameters)
- Return an integer result
- Produce results identical to the evaluator for all valid inputs, respecting each node's data type width
- Execute as native machine code — not as interpreted Python

All node types defined in `nodes.py` must be supported.

Tests are at `/tests/test_state.py`.