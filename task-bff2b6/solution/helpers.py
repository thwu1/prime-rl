from typing import List, Sequence, Union

import libcst as cst
from libcst import matchers as m


def with_added_imports(
    module_node: cst.Module, import_nodes: Sequence[Union[cst.Import, cst.ImportFrom]]
) -> cst.Module:
    """
    Adds new import statements after the first import in the module.
    """
    updated_body: List[Union[cst.SimpleStatementLine, cst.BaseCompoundStatement]] = []
    added_import = False
    for line in module_node.body:
        updated_body.append(line)
        if not added_import and _is_import_line(line):
            for import_node in import_nodes:
                updated_body.append(cst.SimpleStatementLine(body=tuple([import_node])))
            added_import = True

    if not added_import:
        raise RuntimeError("Failed to add imports")

    return module_node.with_changes(body=tuple(updated_body))


def _is_import_line(
    line: Union[cst.SimpleStatementLine, cst.BaseCompoundStatement]
) -> bool:
    return m.matches(line, m.SimpleStatementLine(body=[m.Import() | m.ImportFrom()]))


def name_attr_possibilities(tag: str) -> List[Union[m.Name, m.Attribute]]:
    """
    Given a dotted path like "tornado.gen.coroutine", generates LibCST matcher
    objects for all suffix variants:
      - tornado.gen.coroutine  (full path)
      - gen.coroutine          (partial path)
      - coroutine              (just the name)

    This allows import-agnostic matching: we can detect @tornado.gen.coroutine,
    @gen.coroutine, or @coroutine without resolving imports.

    LibCST represents dotted names as nested Attribute nodes:
      tornado.gen.coroutine -> Attribute(value=Attribute(value=Name("tornado"),
                                          attr=Name("gen")),
                                attr=Name("coroutine"))

    So for each suffix we build the corresponding nested matcher structure.
    """

    def _make_name_or_attribute(parts: List[str]) -> Union[m.Name, m.Attribute]:
        if not parts:
            raise RuntimeError("Expected a non empty list of strings")

        if len(parts) == 1:
            return m.Name(parts[0])

        if len(parts) == 2:
            return m.Attribute(value=m.Name(parts[0]), attr=m.Name(parts[1]))

        value = _make_name_or_attribute(parts[:-1])
        attr = _make_name_or_attribute(parts[-1:])
        return m.Attribute(value=value, attr=attr)

    parts = tag.split(".")
    return [_make_name_or_attribute(parts[start:]) for start in range(len(parts))]


def some_version_of(tag: str) -> m.OneOf[m.Union[m.Name, m.Attribute]]:
    """
    Returns a matcher that matches any import-style variant of the given
    dotted path. Wraps name_attr_possibilities in m.OneOf.
    """
    return m.OneOf(*name_attr_possibilities(tag))
