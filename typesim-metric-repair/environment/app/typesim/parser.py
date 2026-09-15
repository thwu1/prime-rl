"""Type annotation string parser.

Parses Python type annotation strings into TypeNode tree structures.
Supports: int, str, float, bool, bytes, None, Any, object, complex,
          List[T], Dict[K, V], Set[T], FrozenSet[T], Tuple[T, ...],
          Tuple[T1, T2], Union[T1, T2, ...], Optional[T]

Callable[[P1, ...], R] is NOT yet supported and must be implemented.
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
    """Split comma-separated type arguments respecting bracket nesting depth.

    Unlike a naive str.split(', '), this correctly handles cases like
    'str, Dict[int, float]' -> ['str', 'Dict[int, float]'].
    """
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
    """Parse a type annotation string into a TypeNode tree.

    Examples:
        >>> parse_type("int")
        TypeNode(name='int', args=[], is_variadic=False)
        >>> parse_type("List[int]")
        TypeNode(name='List', args=[TypeNode(name='int', ...)], is_variadic=False)
    """
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

    # Callable types: NOT YET IMPLEMENTED
    # You must design the tree representation and parsing logic.
    if base_name == "Callable":
        raise NotImplementedError(
            "Callable type parsing is not implemented. "
            "Design the tree representation and implement parsing for "
            "Callable[[P1, ..., Pn], R] syntax. See /app/spec.md section 3."
        )

    # Handle Optional[X] -> Union[X, None]
    if base_name == "Optional":
        raw_args = _split_args(inner)
        if len(raw_args) != 1:
            raise ValueError(f"Optional expects 1 argument, got {len(raw_args)}")
        inner_type = parse_type(raw_args[0])
        result = TypeNode(name="Union", args=[inner_type, TypeNode(name="None")])
        # Flatten if inner_type is itself a Union
        flat_args = []
        for a in result.args:
            if a.name == "Union":
                flat_args.extend(a.args)
            else:
                flat_args.append(a)
        result.args = flat_args
        return result

    # Use bracket-aware splitting for all generic types
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
