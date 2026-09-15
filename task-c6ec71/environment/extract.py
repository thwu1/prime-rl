"""Extract structural information from accumulated segment states."""


def extract_structure(tokens, accumulated):
    """
    Given the original bracket string and the accumulated segment states,
    extract matching pairs, nesting depths, and parent relationships.
    """
    n = len(tokens)
    matches = [-1] * n
    parents = [-1] * n
    depths = [0] * n

    for i in range(n):
        if tokens[i] == '[':
            # Depth = number of open brackets on the stack before this one
            depths[i] = len(accumulated[i].pushes) - 1

            # Parent = top of stack before this bracket was pushed
            if i == 0:
                parents[i] = (
                    accumulated[i].pushes[-2]
                    if len(accumulated[i].pushes) >= 2
                    else -1
                )
            else:
                prev_pushes = accumulated[i - 1].pushes
                parents[i] = prev_pushes[-1] if prev_pushes else -1

        elif tokens[i] == ']':
            # Depth = remaining stack size after this bracket is processed
            depths[i] = max(0, len(accumulated[i].pushes) - 1)

            # Match = the open bracket on top of the stack before popping
            if i > 0 and accumulated[i - 1].pushes:
                match_idx = accumulated[i - 1].pushes[-1]
                matches[i] = match_idx
                matches[match_idx] = i
            else:
                matches[i] = -1

    # Propagate parents to close brackets
    for i in range(n):
        if tokens[i] == ']':
            if matches[i] != -1:
                parents[i] = parents[matches[i]]
            else:
                parents[i] = -1

    return {"matches": matches, "parents": parents, "depths": depths}
