#!/usr/bin/env python3
"""
ChocoPy Type System Implementation.

This module implements ChocoPy v2.2 type system operations.
It requires a class hierarchy JSON file.

NOTE: This implementation contains bugs that must be diagnosed and fixed.
"""

import json
import sys
from typing import Optional, Dict, List, Tuple, Any


class ChocoPyTypeSystem:
    """Implements ChocoPy type system operations."""

    NONE_TYPE = "<None>"
    EMPTY_TYPE = "<Empty>"
    PRIMITIVE_VALUE_TYPES = frozenset({"int", "bool", "str"})
    BUILTIN_TYPE_TAGS = {"int": 1, "bool": 2, "str": 3}
    LIST_TYPE_TAG = -1

    def __init__(self, hierarchy_path: str):
        with open(hierarchy_path) as f:
            data = json.load(f)

        self._raw_classes = data["classes"]
        self._parent: Dict[str, Optional[str]] = {}
        self._class_order: List[str] = []

        for cls_name, cls_info in self._raw_classes.items():
            self._parent[cls_name] = cls_info.get("super")
            self._class_order.append(cls_name)

        # Compute type tags
        self._type_tags: Dict[str, int] = {}
        next_tag = 4
        for cls_name in self._class_order:
            if cls_name in self.BUILTIN_TYPE_TAGS:
                self._type_tags[cls_name] = self.BUILTIN_TYPE_TAGS[cls_name]
            elif cls_name != "object":
                self._type_tags[cls_name] = next_tag
                next_tag += 1

        # Build dispatch tables and attribute layouts
        self._dispatch_tables: Dict[str, List[Tuple[str, str]]] = {}
        self._attr_layouts: Dict[str, List[Tuple[str, str]]] = {}
        for cls_name in self._class_order:
            self._build_dispatch_table(cls_name)
            self._build_attr_layout(cls_name)

    # ================================================================
    # Internal layout builders
    # ================================================================

    def _build_dispatch_table(self, cls_name: str):
        if cls_name in self._dispatch_tables:
            return

        parent = self._parent.get(cls_name)
        if parent is None:
            parent_table: List[Tuple[str, str]] = []
        else:
            if parent not in self._dispatch_tables:
                self._build_dispatch_table(parent)
            parent_table = list(self._dispatch_tables[parent])

        table = list(parent_table)
        cls_methods = self._raw_classes[cls_name].get("methods", {})

        for method_name in cls_methods:
            found = False
            for i, (existing_method, _defining_class) in enumerate(table):
                if existing_method == method_name:
                    table[i] = (method_name, cls_name)
                    found = True
                    break
            if not found:
                table.append((method_name, cls_name))

        self._dispatch_tables[cls_name] = table

    def _build_attr_layout(self, cls_name: str):
        if cls_name in self._attr_layouts:
            return

        parent = self._parent.get(cls_name)
        if parent is None:
            parent_attrs: List[Tuple[str, str]] = []
        else:
            if parent not in self._attr_layouts:
                self._build_attr_layout(parent)
            parent_attrs = list(self._attr_layouts[parent])

        layout = list(parent_attrs)
        cls_attrs = self._raw_classes[cls_name].get("attrs", {})
        for attr_name, attr_type in cls_attrs.items():
            layout.append((attr_name, attr_type))

        self._attr_layouts[cls_name] = layout

    # ================================================================
    # Type classification helpers
    # ================================================================

    def is_class_type(self, t: str) -> bool:
        return t in self._raw_classes

    def is_list_type(self, t: str) -> bool:
        return len(t) >= 3 and t[0] == "[" and t[-1] == "]"

    def list_element_type(self, t: str) -> str:
        assert self.is_list_type(t), f"Not a list type: {t}"
        return t[1:-1]

    def _ancestors(self, cls_name: str) -> List[str]:
        """Return [cls_name, parent, grandparent, ..., object]."""
        result = []
        current: Optional[str] = cls_name
        while current is not None:
            result.append(current)
            current = self._parent.get(current)
        return result

    # ================================================================
    # Core type relations
    # ================================================================

    def conforms(self, t1: str, t2: str) -> bool:
        """Check t1 <= t2 (conformance / subtyping)."""
        if t1 == t2:
            return True

        if t1 == self.NONE_TYPE:
            return t2 == "object"
        if t1 == self.EMPTY_TYPE:
            return t2 == "object"

        if self.is_class_type(t1) and self.is_class_type(t2):
            return t2 in self._ancestors(t1)

        return False

    def is_assignable(self, t1: str, t2: str) -> bool:
        """Check t1 <=_a t2 (assignment compatibility)."""
        # Rule 1: ordinary subtyping
        if self.conforms(t1, t2):
            return True

        # Rule 2: <None> assignable to anything except int, bool, str
        if t1 == self.NONE_TYPE and t2 not in self.PRIMITIVE_VALUE_TYPES:
            return True

        # Rule 3: <Empty> assignable to any list type
        if t1 == self.EMPTY_TYPE and self.is_list_type(t2):
            return True

        # Rule 4: [<None>] assignable to [T] when <None> <=_a T
        if self.is_list_type(t1) and self.is_list_type(t2):
            elem1 = self.list_element_type(t1)
            if elem1 == self.NONE_TYPE:
                return True

        return False

    def join(self, t1: str, t2: str) -> str:
        """Compute t1 join t2 (least upper bound using <=_a)."""
        if self.is_assignable(t1, t2):
            return t2

        # Both class types: find LCA
        if self.is_class_type(t1) and self.is_class_type(t2):
            ancestors1 = self._ancestors(t1)
            ancestors2_set = set(self._ancestors(t2))
            for a in ancestors1:
                if a in ancestors2_set:
                    return a

        return "object"

    # ================================================================
    # Method / attribute resolution
    # ================================================================

    def resolve_method(self, class_name: str, method_name: str) -> Optional[Dict]:
        """Resolve method by walking up the hierarchy.

        Returns {"params": [...], "return": "...", "defining_class": "..."} or None.
        """
        if not self.is_class_type(class_name):
            return None

        for cls in self._ancestors(class_name):
            cls_methods = self._raw_classes[cls].get("methods", {})
            if method_name in cls_methods:
                info = cls_methods[method_name]
                return {
                    "params": info["params"],
                    "return": info["return"],
                    "defining_class": cls,
                }
        return None

    def check_method_override(self, child_class: str, method_name: str) -> bool:
        """Check if a method override in child_class is valid.

        Valid iff return type matches and all param types except the first (self)
        are exactly the same as the overridden method.
        Returns True if the method is new (not overriding) or if the override is valid.
        Returns False if the override violates the rules.
        """
        if child_class not in self._raw_classes:
            return False
        child_methods = self._raw_classes[child_class].get("methods", {})
        if method_name not in child_methods:
            return False

        parent = self._parent.get(child_class)
        if parent is None:
            return True

        # Find method in parent hierarchy
        parent_method = None
        for cls in self._ancestors(parent):
            cls_methods = self._raw_classes[cls].get("methods", {})
            if method_name in cls_methods:
                parent_method = cls_methods[method_name]
                break

        if parent_method is None:
            return True  # Not overriding anything

        child_method = child_methods[method_name]

        if child_method["return"] != parent_method["return"]:
            return False
        if len(child_method["params"]) != len(parent_method["params"]):
            return False
        return True

    def type_of_attr_access(self, obj_type: str, attr_name: str) -> Optional[str]:
        """Type of obj.attr (attribute access)."""
        if not self.is_class_type(obj_type):
            return None
        for cls in self._ancestors(obj_type):
            cls_attrs = self._raw_classes[cls].get("attrs", {})
            if attr_name in cls_attrs:
                return cls_attrs[attr_name]
        return None

    # ================================================================
    # Expression type operations
    # ================================================================

    def type_of_binary_op(self, op: str, t1: str, t2: str) -> Optional[str]:
        """Result type of t1 op t2, or None if invalid."""
        if op in ("+", "-", "*", "//", "%"):
            if t1 == "int" and t2 == "int":
                return "int"
            if op == "+":
                if t1 == "str" and t2 == "str":
                    return "str"
                if self.is_list_type(t1) and self.is_list_type(t2):
                    e1 = self.list_element_type(t1)
                    e2 = self.list_element_type(t2)
                    return f"[{self.join(e1, e2)}]"
            return None

        if op in ("<", "<=", ">", ">="):
            if t1 == "int" and t2 == "int":
                return "bool"
            return None

        if op in ("==", "!="):
            if t1 == t2 and t1 in self.PRIMITIVE_VALUE_TYPES:
                return "bool"
            return None

        if op in ("and", "or"):
            if t1 == "bool" and t2 == "bool":
                return "bool"
            return None

        if op == "is":
            if t1 not in self.PRIMITIVE_VALUE_TYPES or t2 not in self.PRIMITIVE_VALUE_TYPES:
                return "bool"
            return None

        return None

    def type_of_unary_op(self, op: str, t: str) -> Optional[str]:
        """Result type of unary op on t, or None if invalid."""
        if op == "-" and t == "int":
            return "int"
        if op == "not" and t == "bool":
            return "bool"
        return None

    def type_of_list_display(self, elem_types: List[str]) -> str:
        """Type of [e1, e2, ...] given element types."""
        if not elem_types:
            return self.EMPTY_TYPE
        result = elem_types[0]
        for t in elem_types[1:]:
            result = self.join(result, t)
        return f"[{result}]"

    def type_of_conditional(self, t_then: str, t_else: str) -> str:
        """Type of (e1 if cond else e2)."""
        return self.join(t_then, t_else)

    def type_of_method_call(
        self, receiver_type: str, method_name: str, arg_types: List[str]
    ) -> Optional[str]:
        """Return type of receiver.method(args), or None if invalid."""
        if not self.is_class_type(receiver_type):
            return None

        method = self.resolve_method(receiver_type, method_name)
        if method is None:
            return None

        expected_params = method["params"][1:]  # skip self

        if len(arg_types) != len(expected_params):
            return None

        for arg_t, param_t in zip(arg_types, expected_params):
            if not self.is_assignable(arg_t, param_t):
                return None

        return method["return"]

    def type_of_index(self, container_type: str, index_type: str) -> Optional[str]:
        """Type of container[index], or None if invalid."""
        if index_type != "int":
            return None
        if container_type == "str":
            return "str"
        if self.is_list_type(container_type):
            return self.list_element_type(container_type)
        return None

    def type_of_constructor(self, class_name: str) -> Optional[str]:
        """Type of ClassName() expression."""
        if self.is_class_type(class_name):
            return class_name
        return None

    # ================================================================
    # Object layout queries
    # ================================================================

    def get_type_tag(self, type_name: str) -> Optional[int]:
        """Type tag for a type, or None if not applicable."""
        if self.is_list_type(type_name):
            return self.LIST_TYPE_TAG
        return self._type_tags.get(type_name)

    def get_dispatch_table(self, class_name: str) -> Optional[List[Tuple[str, str]]]:
        """Dispatch table as list of (method_name, defining_class)."""
        return self._dispatch_tables.get(class_name)

    def get_attr_layout(self, class_name: str) -> Optional[List[Tuple[str, str]]]:
        """Attribute layout as list of (attr_name, attr_type), parent attrs first."""
        return self._attr_layouts.get(class_name)

    def get_object_size(self, class_name: str) -> Optional[int]:
        """Object size in words: 3 (header) + num_attributes."""
        layout = self._attr_layouts.get(class_name)
        if layout is None:
            return None
        return 3 + len(layout)
