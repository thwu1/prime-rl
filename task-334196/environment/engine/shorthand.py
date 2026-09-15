"""CSS shorthand property expansion.

Handles margin and padding shorthands with 1-4 value syntax.

"""


def expand_shorthand(property_name, value):
    """Expand CSS shorthand properties to longhand properties.

    Returns a dict mapping longhand property names to values.
    Non-shorthand properties are returned as {property_name: value}.
    """
    if property_name in ("margin", "padding"):
        parts = value.split()
        prefix = property_name
        if len(parts) == 1:
            v = parts[0]
            return {
                f"{prefix}-top": v,
                f"{prefix}-right": v,
                f"{prefix}-bottom": v,
                f"{prefix}-left": v,
            }
        elif len(parts) == 2:
            return {
                f"{prefix}-top": parts[0],
                f"{prefix}-right": parts[1],
                f"{prefix}-bottom": parts[0],
                f"{prefix}-left": parts[1],
            }
        elif len(parts) == 3:
            return {
                f"{prefix}-top": parts[0],
                f"{prefix}-right": parts[1],
                f"{prefix}-bottom": parts[2],
                f"{prefix}-left": parts[1],
            }
        elif len(parts) == 4:
            return {
                f"{prefix}-top": parts[0],
                f"{prefix}-right": parts[1],
                f"{prefix}-bottom": parts[2],
                f"{prefix}-left": parts[3],
            }
    return {property_name: value}
