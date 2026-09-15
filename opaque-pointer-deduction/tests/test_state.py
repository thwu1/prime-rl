
"""
Tests for the LLVM IR opaque-pointer type deduction analysis.
Verifies that /app/results.json contains correct pointee types
for pointer-valued SSA variables across all input IR files.
"""

import json
import os
import pytest

RESULTS_PATH = "/app/results.json"


@pytest.fixture(scope="session")
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found: {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    assert isinstance(data, dict), "results.json must be a JSON object"
    return data


def get_type(results, filename, func, var):
    """Look up the deduced pointee type for a variable."""
    assert filename in results, f"File '{filename}' not in results"
    assert func in results[filename], (
        f"Function '{func}' not in results for '{filename}'. "
        f"Available: {list(results[filename].keys())}"
    )
    assert var in results[filename][func], (
        f"Variable '{var}' not in '{func}' results for '{filename}'. "
        f"Available: {list(results[filename][func].keys())}"
    )
    return results[filename][func][var]


# =============================================================================
# basic.ll — local type deduction (alloca, load, store, GEP)
# =============================================================================


class TestAllocaTypes:
    """alloca T -> result points to T"""

    def test_alloca_i32(self, results):
        assert get_type(results, "basic.ll", "scalar_ops", "%x") == "i32"

    def test_alloca_i64(self, results):
        assert get_type(results, "basic.ll", "scalar_ops", "%y") == "i64"

    def test_alloca_float(self, results):
        assert get_type(results, "basic.ll", "scalar_ops", "%f") == "float"


class TestStructGEP:
    """GEP into flat struct fields"""

    def test_point_base_ptr(self, results):
        assert get_type(results, "basic.ll", "point_get_x", "%p") == "%struct.Point"

    def test_point_field_ptr(self, results):
        assert get_type(results, "basic.ll", "point_get_x", "%xptr") == "double"

    def test_point_set_base(self, results):
        assert get_type(results, "basic.ll", "point_set", "%p") == "%struct.Point"

    def test_point_set_yfield(self, results):
        assert get_type(results, "basic.ll", "point_set", "%yptr") == "double"


class TestNestedStructGEP:
    """GEP through nested named structs (Rect -> Point -> double).
    Requires resolving named types at intermediate GEP levels."""

    def test_rect_base(self, results):
        assert get_type(results, "basic.ll", "rect_origin_x", "%r") == "%struct.Rect"

    def test_rect_nested_double(self, results):
        assert get_type(results, "basic.ll", "rect_origin_x", "%ox") == "double"

    def test_rect_corner_base(self, results):
        assert get_type(results, "basic.ll", "rect_set_corner", "%r") == "%struct.Rect"

    def test_rect_corner_field(self, results):
        assert get_type(results, "basic.ll", "rect_set_corner", "%cx") == "double"


class TestArrayAccess:
    """GEP for simple array element access"""

    def test_array_base(self, results):
        assert get_type(results, "basic.ll", "array_sum", "%arr") == "i32"

    def test_array_element(self, results):
        assert get_type(results, "basic.ll", "array_sum", "%ep") == "i32"


class TestPointerToPointer:
    """load ptr from ptr-to-ptr"""

    def test_pp_outer(self, results):
        assert get_type(results, "basic.ll", "deref_pp", "%pp") == "ptr"

    def test_pp_inner(self, results):
        assert get_type(results, "basic.ll", "deref_pp", "%p") == "i32"


class TestColorStruct:
    """GEP into 4-field byte struct"""

    def test_color_base(self, results):
        assert get_type(results, "basic.ll", "get_alpha", "%c") == "%struct.Color"

    def test_color_alpha_field(self, results):
        assert get_type(results, "basic.ll", "get_alpha", "%aptr") == "i8"


class TestNestedGEPReturnOnly:
    """GEP through nested named structs where result is returned, not loaded.
    Type evidence comes ONLY from correct GEP resolution — no load/store backup.
    Rect -> Point -> double, Panel -> Widget -> double/ptr."""

    def test_rect_origin_ptr_base(self, results):
        assert get_type(results, "basic.ll", "rect_origin_ptr", "%r") == "%struct.Rect"

    def test_rect_origin_ptr_result(self, results):
        assert get_type(results, "basic.ll", "rect_origin_ptr", "%op") == "double"

    def test_rect_corner_y_ptr_base(self, results):
        assert get_type(results, "basic.ll", "rect_corner_y_ptr", "%r") == "%struct.Rect"

    def test_rect_corner_y_ptr_result(self, results):
        assert get_type(results, "basic.ll", "rect_corner_y_ptr", "%cy") == "double"


# =============================================================================
# advanced.ll — globals, linked list, matrix, interprocedural
# =============================================================================


class TestGlobalVariables:
    """Types deduced from global variable usage"""

    def test_global_i32(self, results):
        assert get_type(results, "advanced.ll", "inc_count", "@g_count") == "i32"

    def test_global_array(self, results):
        assert get_type(results, "advanced.ll", "clear_buffer", "@g_buffer") == "[256 x i8]"

    def test_global_array_element(self, results):
        assert get_type(results, "advanced.ll", "clear_buffer", "%p") == "i8"


class TestLinkedList:
    """Linked list with recursive struct type"""

    def test_list_cur(self, results):
        assert get_type(results, "advanced.ll", "list_sum", "%cur") == "%struct.Node"

    def test_list_val_ptr(self, results):
        assert get_type(results, "advanced.ll", "list_sum", "%val_ptr") == "i32"

    def test_list_next_field(self, results):
        assert get_type(results, "advanced.ll", "list_sum", "%next_ptr") == "ptr"


class TestMatrixStruct:
    """Struct with pointer data field + double array access"""

    def test_matrix_base(self, results):
        assert get_type(results, "advanced.ll", "matrix_get", "%m") == "%struct.Matrix"

    def test_matrix_cols_field(self, results):
        assert get_type(results, "advanced.ll", "matrix_get", "%cols_ptr") == "i32"

    def test_matrix_data_field(self, results):
        assert get_type(results, "advanced.ll", "matrix_get", "%data_ptr") == "ptr"

    def test_matrix_data_usage(self, results):
        """data loaded as ptr, then used in GEP double -> deduced as double"""
        assert get_type(results, "advanced.ll", "matrix_get", "%data") == "double"

    def test_matrix_elem(self, results):
        assert get_type(results, "advanced.ll", "matrix_get", "%elem_ptr") == "double"


class TestInterproceduralLocal:
    """Type deduction within callee/caller from local evidence"""

    def test_init_node_param(self, results):
        assert get_type(results, "advanced.ll", "init_node", "%n") == "%struct.Node"

    def test_create_node_alloca(self, results):
        assert get_type(results, "advanced.ll", "create_node", "%n") == "%struct.Node"

    def test_store_value_dst(self, results):
        assert get_type(results, "advanced.ll", "store_value", "%dst") == "double"


class TestInterproceduralChain:
    """Type propagation across multi-hop call chain:
    caller -> process -> store_value
    store_value.%dst = double -> process.%target = double -> caller.%buf = double
    """

    def test_process_target(self, results):
        assert get_type(results, "advanced.ll", "process", "%target") == "double"

    def test_caller_buf(self, results):
        assert get_type(results, "advanced.ll", "caller", "%buf") == "double"


class TestPHIPropagation:
    """PHI node back-edge propagation:
    %cur = phi [%head, ...], [%next, ...]
    %cur -> %struct.Node (from GEP) -> %head and %next should also be %struct.Node
    Requires backward propagation from PHI result to source operands.
    """

    def test_head_from_phi(self, results):
        assert get_type(results, "advanced.ll", "list_sum", "%head") == "%struct.Node"


# =============================================================================
# edge_cases.ll — recursive calls, arrays in structs, select
# =============================================================================


class TestTreeRecursive:
    """Binary tree with recursive self-calls"""

    def test_tree_node_base(self, results):
        assert get_type(results, "edge_cases.ll", "tree_depth", "%node") == "%struct.Tree"

    def test_tree_left_field(self, results):
        assert get_type(results, "edge_cases.ll", "tree_depth", "%lp") == "ptr"

    def test_tree_right_field(self, results):
        assert get_type(results, "edge_cases.ll", "tree_depth", "%rp") == "ptr"


class TestRecursiveCallPropagation:
    """Interprocedural propagation through recursive calls:
    tree_depth calls itself with %left/%right -> %node is %struct.Tree
    Requires callee-to-caller propagation direction.
    """

    def test_tree_left_recursive(self, results):
        assert get_type(results, "edge_cases.ll", "tree_depth", "%left") == "%struct.Tree"

    def test_tree_right_recursive(self, results):
        assert get_type(results, "edge_cases.ll", "tree_depth", "%right") == "%struct.Tree"


class TestTaggedArrayInStruct:
    """Struct with embedded array: { i32, [4 x double] }"""

    def test_tagged_base(self, results):
        assert get_type(results, "edge_cases.ll", "tagged_get", "%t") == "%struct.Tagged"

    def test_tagged_arr_base(self, results):
        assert get_type(results, "edge_cases.ll", "tagged_get", "%arr_base") == "double"

    def test_tagged_elem(self, results):
        assert get_type(results, "edge_cases.ll", "tagged_get", "%elem") == "double"


class TestArrayOfStructs:
    """alloca [10 x %struct.Pair], GEP into array then into struct fields"""

    def test_pairs_alloca(self, results):
        assert get_type(results, "edge_cases.ll", "pair_sum_array", "%pairs") == "[10 x %struct.Pair]"

    def test_pairs_first(self, results):
        assert get_type(results, "edge_cases.ll", "pair_sum_array", "%first") == "%struct.Pair"

    def test_pairs_field_a(self, results):
        assert get_type(results, "edge_cases.ll", "pair_sum_array", "%f_a") == "i64"

    def test_pairs_field_b(self, results):
        assert get_type(results, "edge_cases.ll", "pair_sum_array", "%f_b") == "i64"


class TestSelectPropagation:
    """select i1 %c, ptr %a, ptr %b -> propagate from load through select.
    Requires select instruction parsing and bidirectional propagation.
    """

    def test_select_result(self, results):
        assert get_type(results, "edge_cases.ll", "conditional_load", "%chosen") == "i32"

    def test_select_source_a(self, results):
        assert get_type(results, "edge_cases.ll", "conditional_load", "%a") == "i32"

    def test_select_source_b(self, results):
        assert get_type(results, "edge_cases.ll", "conditional_load", "%b") == "i32"


# =============================================================================
# interop.ll — cross-function type flow, nested struct panels
# =============================================================================


class TestWidgetBasic:
    """Direct GEP type evidence for Widget struct"""

    def test_widget_set_value_param(self, results):
        assert get_type(results, "interop.ll", "widget_set_value", "%w") == "%struct.Widget"

    def test_widget_set_value_field(self, results):
        assert get_type(results, "interop.ll", "widget_set_value", "%vp") == "double"


class TestCalleeToCallerPropagation:
    """init_widget has no local type evidence for %w.
    widget_set_value.%w = %struct.Widget (from GEP) must flow back to
    init_widget.%w via callee-to-caller interprocedural propagation.
    """

    def test_init_widget_param(self, results):
        assert get_type(results, "interop.ll", "init_widget", "%w") == "%struct.Widget"


class TestReadWidgetValue:
    """Direct GEP evidence in read_widget_value"""

    def test_read_widget_param(self, results):
        assert get_type(results, "interop.ll", "read_widget_value", "%w") == "%struct.Widget"

    def test_read_widget_field(self, results):
        assert get_type(results, "interop.ll", "read_widget_value", "%vp") == "double"


class TestNestedStructPanel:
    """GEP through Panel -> Widget -> double field.
    Requires resolving named types at intermediate GEP index levels:
    %struct.Panel field 0 is %struct.Widget, which must be resolved to
    { i32, double, ptr } before indexing field 1 to get double.
    """

    def test_panel_param(self, results):
        assert get_type(results, "interop.ll", "panel_primary_value", "%p") == "%struct.Panel"

    def test_panel_nested_field(self, results):
        assert get_type(results, "interop.ll", "panel_primary_value", "%vp") == "double"


class TestPanelGEPReturnOnly:
    """GEP through Panel -> Widget fields where result is returned, not loaded.
    Type evidence comes ONLY from GEP resolution — no load/store backup.
    Requires named type resolution at intermediate GEP levels."""

    def test_panel_value_ptr_base(self, results):
        assert get_type(results, "interop.ll", "panel_value_ptr", "%p") == "%struct.Panel"

    def test_panel_value_ptr_result(self, results):
        assert get_type(results, "interop.ll", "panel_value_ptr", "%vp") == "double"

    def test_panel_label_ptr_base(self, results):
        assert get_type(results, "interop.ll", "panel_label_ptr", "%p") == "%struct.Panel"

    def test_panel_label_ptr_result(self, results):
        assert get_type(results, "interop.ll", "panel_label_ptr", "%lp") == "ptr"
