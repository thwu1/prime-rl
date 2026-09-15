"""DOM tree representation and utilities."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DOMNode:
    tag: str
    id: Optional[str] = None
    classes: list = field(default_factory=list)
    attributes: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    parent: Optional["DOMNode"] = None
    child_index: int = 0

    def element_children(self):
        return [c for c in self.children if isinstance(c, DOMNode)]

    def path_segment(self):
        if self.id:
            return f"{self.tag}#{self.id}"
        if self.classes:
            sorted_classes = sorted(self.classes)
            return self.tag + "." + ".".join(sorted_classes)
        return self.tag

    def full_path(self):
        parts = []
        node = self
        while node:
            parts.append(node.path_segment())
            node = node.parent
        parts.reverse()
        return " > ".join(parts)

    def ancestors(self):
        node = self.parent
        while node:
            yield node
            node = node.parent

    def preceding_siblings(self):
        if not self.parent:
            return []
        siblings = self.parent.element_children()
        idx = None
        for i, s in enumerate(siblings):
            if s is self:
                idx = i
                break
        if idx is None or idx == 0:
            return []
        return siblings[:idx]

    def immediately_preceding_sibling(self):
        sibs = self.preceding_siblings()
        if sibs:
            return sibs[-1]
        return None

    def descendants(self):
        for c in self.children:
            if isinstance(c, DOMNode):
                yield c
                yield from c.descendants()


def build_dom(data, parent=None):
    if isinstance(data, str):
        return data
    node = DOMNode(
        tag=data.get("tag", ""),
        id=data.get("id"),
        classes=data.get("classes", []),
        attributes=data.get("attributes", {}),
        parent=parent,
    )
    idx = 0
    for child_data in data.get("children", []):
        child = build_dom(child_data, parent=node)
        if isinstance(child, DOMNode):
            child.child_index = idx
            idx += 1
        node.children.append(child)
    return node


def collect_elements(node):
    elements = []
    if isinstance(node, DOMNode):
        elements.append(node)
        for c in node.children:
            elements.extend(collect_elements(c))
    return elements
