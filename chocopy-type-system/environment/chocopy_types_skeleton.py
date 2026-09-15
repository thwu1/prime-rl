#!/usr/bin/env python3
"""
ChocoPy Type System Implementation — Skeleton.

This module defines the ChocoPyTypeSystem class API.
All core type-system methods are stubs that raise NotImplementedError.
Implement them according to the specification in /app/spec.md.

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

        # Compute type tags: builtins have fixed tags, user-defined start at 4
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
    # Internal layout builders (provided)
    # ================================================================

    def _build_dispatch_table(self, cls_name: str):
        """Build dispatch table: parent slots first, overrides in-place, new methods appended."""
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
        """Build attribute layout: parent attrs first, then own attrs."""
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
    # Type classification helpers (provided)
    # ================================================================

    def is_class_type(self, t: str) -> bool:
        """True if t is a defined class name."""
        return t in self._raw_classes

    def is_list_type(self, t: str) -> bool:
        """True if t is a list type like '[int]' or '[[A]]'."""
        return len(t) >= 3 and t[0] == "[" and t[-1] == "]"

    def list_element_type(self, t: str) -> str:
        """Extract element type: '[int]' -> 'int', '[[A]]' -> '[A]'."""
        assert self.is_list_type(t), f"Not a list type: {t}"
        return t[1:-1]

    def _ancestors(self, cls_name: str) -> List[str]:
        """Return ancestor chain [cls_name, parent, grandparent, ..., object]."""
        result = []
        current: Optional[str] = cls_name
        while current is not None:
            result.append(current)
            current = self._parent.get(current)
        return result

    # ================================================================
    # Core type relations — implement per spec.md sections 2-4
    # ================================================================

    def conforms(self, t1: str, t2: str) -> bool:
        """Check t1 <= t2 (conformance / subtyping). See spec section 2."""
        raise NotImplementedError

    def is_assignable(self, t1: str, t2: str) -> bool:
        """Check t1 <=_a t2 (assignment compatibility). See spec section 3."""
        raise NotImplementedError

    def join(self, t1: str, t2: str) -> str:
        """Compute t1 ⊔ t2 (least upper bound using <=_a). See spec section 4."""
        raise NotImplementedError

    # ================================================================
    # Method / attribute resolution — implement per spec.md sections 5-6
    # ================================================================

    def resolve_method(self, class_name: str, method_name: str) -> Optional[Dict]:
        """Resolve method by walking up the hierarchy.

        Returns {"params": [...], "return": "...", "defining_class": "..."} or None.
        See spec section 5.12 and 7.4.
        """
        raise NotImplementedError

    def check_method_override(self, child_class: str, method_name: str) -> bool:
        """Check if a method override in child_class is valid per spec section 6.

        Returns True if the method is new (not overriding) or if the override is valid.
        Returns False if the override violates the rules.
        """
        raise NotImplementedError

    def type_of_attr_access(self, obj_type: str, attr_name: str) -> Optional[str]:
        """Type of obj.attr (attribute access). See spec section 5.11."""
        raise NotImplementedError

    # ================================================================
    # Expression type operations — implement per spec.md section 5
    # ================================================================

    def type_of_binary_op(self, op: str, t1: str, t2: str) -> Optional[str]:
        """Result type of t1 op t2, or None if invalid.

        Covers arithmetic (5.1), comparisons (5.2), equality (5.3),
        logical (5.4), string ops (5.5), 'is' (5.6), and list ops (5.7).
        """
        raise NotImplementedError

    def type_of_unary_op(self, op: str, t: str) -> Optional[str]:
        """Result type of unary op on t, or None if invalid. See spec 5.1, 5.4."""
        raise NotImplementedError

    def type_of_list_display(self, elem_types: List[str]) -> str:
        """Type of [e1, e2, ...] given element types. See spec section 5.8."""
        raise NotImplementedError

    def type_of_conditional(self, t_then: str, t_else: str) -> str:
        """Type of (e1 if cond else e2). See spec section 5.9."""
        raise NotImplementedError

    def type_of_method_call(
        self, receiver_type: str, method_name: str, arg_types: List[str]
    ) -> Optional[str]:
        """Return type of receiver.method(args), or None if invalid. See spec 5.12."""
        raise NotImplementedError

    def type_of_index(self, container_type: str, index_type: str) -> Optional[str]:
        """Type of container[index], or None if invalid. See spec 5.5, 5.7."""
        raise NotImplementedError

    def type_of_constructor(self, class_name: str) -> Optional[str]:
        """Type of ClassName() expression. See spec section 5.10."""
        raise NotImplementedError

    # ================================================================
    # Object layout queries (provided — delegate to precomputed data)
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
