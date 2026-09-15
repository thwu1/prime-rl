"""Type annotation string parser — complete implementation.

Handles all type constructs including Callable[[P1, ..., Pn], R]
with a grouped parameter representation using a __params__ wrapper node.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List


@dataclass
class TypeNode:
    """Represents a parsed type annotation as a tree node."""
    name: str
    args: List[TypeNode] = field(default_factory=list)
    is_variadic: bool = False

    def __str__(self) -> str:
        if self.name == "Callable":
            # Reconstruct double-bracket syntax: Callable[[P1, ...], R]
            params_node = self.args[0]
            ret_node = self.args[1]
            params_str = ", ".join(str(a) for a in params_node.args)
            return f"Callable[[{params_str}], {ret_node}]"
        if self.name == "Union":
            inner = ", ".join(str(a) for a in self.args)
            return f"Union[{inner}]"
        if not self.args:
            return self.name
        args_str = ", ".join(str(a) for a in self.args)
        if self.is_variadic:
            args_str += ", ..."
        return f"{self.name}[{args_str}]"

    def __eq__(self, other) -> bool:
        if not isinstance(other, TypeNode):
            return False
        return (self.name == other.name
                and self.args == other.args
                and self.is_variadic == other.is_variadic)

    def __hash__(self) -> int:
        return hash(str(self))


def _split_args(inner: str) -> list:
    """Split comma-separated type arguments respecting bracket nesting depth."""
    args = []
    depth = 0
    current = []
    for char in inner:
        if char == '[':
            depth += 1
            current.append(char)
        elif char == ']':
            depth -= 1
            current.append(char)
        elif char == ',' and depth == 0:
            args.append(''.join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        args.append(''.join(current).strip())
    return [a for a in args if a]


def parse_type(type_str: str) -> TypeNode:
    """Parse a type annotation string into a TypeNode tree."""
    type_str = type_str.strip()

    if not type_str:
        raise ValueError("Empty type string")

    bracket_pos = type_str.find('[')

    if bracket_pos == -1:
        return TypeNode(name=type_str)

    base_name = type_str[:bracket_pos].strip()

    if type_str[-1] != ']':
        raise ValueError(f"Malformed type string: {type_str}")

    inner = type_str[bracket_pos + 1:-1]

    # Handle Callable[[P1, ...], R] — double-bracket syntax
    if base_name == "Callable":
        inner = inner.strip()
        if not inner.startswith('['):
            raise ValueError("Callable expects [[params], return] syntax")
        # Find matching ] for the parameter list bracket
        depth = 0
        param_end = -1
        for i, c in enumerate(inner):
            if c == '[':
                depth += 1
            elif c == ']':
                depth -= 1
                if depth == 0:
                    param_end = i
                    break
        if param_end == -1:
            raise ValueError(f"Unmatched bracket in Callable params: {type_str}")
        param_inner = inner[1:param_end]  # content inside [...]
        if param_inner.strip():
            param_types = [parse_type(p) for p in _split_args(param_inner)]
        else:
            param_types = []
        rest = inner[param_end + 1:].strip()
        if rest.startswith(','):
            rest = rest[1:].strip()
        ret_type = parse_type(rest)
        params_node = TypeNode(name="__params__", args=param_types)
        return TypeNode(name="Callable", args=[params_node, ret_type])

    # Handle Optional[X] -> Union[X, None]
    if base_name == "Optional":
        raw_args = _split_args(inner)
        if len(raw_args) != 1:
            raise ValueError(
                f"Optional expects exactly 1 argument, got {len(raw_args)}"
            )
        inner_type = parse_type(raw_args[0])
        result = TypeNode(
            name="Union",
            args=[inner_type, TypeNode(name="None")]
        )
        # Flatten if inner_type is itself a Union
        flat_args = []
        for a in result.args:
            if a.name == "Union":
                flat_args.extend(a.args)
            else:
                flat_args.append(a)
        result.args = flat_args
        return result

    # Use bracket-aware splitting
    raw_args = _split_args(inner)

    parsed_args = []
    is_variadic = False

    for arg in raw_args:
        arg = arg.strip()
        if arg == '...':
            is_variadic = True
            continue
        parsed_args.append(parse_type(arg))

    # Flatten nested unions
    if base_name == "Union":
        flat_args = []
        for a in parsed_args:
            if a.name == "Union":
                flat_args.extend(a.args)
            else:
                flat_args.append(a)
        parsed_args = flat_args

    return TypeNode(name=base_name, args=parsed_args, is_variadic=is_variadic)
