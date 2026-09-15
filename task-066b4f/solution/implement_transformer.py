#!/usr/bin/env python3
"""
Generates the complete TornadoAsyncTransformer implementation.

"""
import os
import textwrap


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


# =============================================================================
# helpers.py — matcher utilities and import insertion
# =============================================================================

helpers_code = textwrap.dedent('''\
    from typing import List, Sequence, Union

    import libcst as cst
    from libcst import matchers as m


    def with_added_imports(
        module_node: cst.Module,
        import_nodes: Sequence[Union[cst.Import, cst.ImportFrom]],
    ) -> cst.Module:
        """
        Adds new import statements after the first import in the module.
        """
        updated_body: List[
            Union[cst.SimpleStatementLine, cst.BaseCompoundStatement]
        ] = []
        added_import = False
        for line in module_node.body:
            updated_body.append(line)
            if not added_import and _is_import_line(line):
                for import_node in import_nodes:
                    updated_body.append(
                        cst.SimpleStatementLine(body=tuple([import_node]))
                    )
                added_import = True

        if not added_import:
            raise RuntimeError("Failed to add imports")

        return module_node.with_changes(body=tuple(updated_body))


    def _is_import_line(
        line: Union[cst.SimpleStatementLine, cst.BaseCompoundStatement],
    ) -> bool:
        return m.matches(
            line, m.SimpleStatementLine(body=[m.Import() | m.ImportFrom()])
        )


    def name_attr_possibilities(tag: str) -> List[Union[m.Name, m.Attribute]]:
        """
        Given a dotted name like "tornado.gen.coroutine", produce matchers for
        every possible import-style reference:
          - tornado.gen.coroutine  (Attribute(Attribute(Name, Name), Name))
          - gen.coroutine          (Attribute(Name, Name))
          - coroutine              (Name)

        This handles the fact that a symbol can be referenced via different
        import styles without needing to track actual imports.
        """

        def _make_name_or_attribute(
            parts: List[str],
        ) -> Union[m.Name, m.Attribute]:
            if not parts:
                raise RuntimeError("Expected a non empty list of strings")
            if len(parts) == 1:
                return m.Name(parts[0])
            if len(parts) == 2:
                return m.Attribute(
                    value=m.Name(parts[0]), attr=m.Name(parts[1])
                )
            value = _make_name_or_attribute(parts[:-1])
            attr = _make_name_or_attribute(parts[-1:])
            return m.Attribute(value=value, attr=attr)

        parts = tag.split(".")
        return [
            _make_name_or_attribute(parts[start:]) for start in range(len(parts))
        ]


    def some_version_of(
        tag: str,
    ) -> m.OneOf[m.Union[m.Name, m.Attribute]]:
        """
        Return a OneOf matcher covering all import-style variants of a dotted name.
        """
        return m.OneOf(*name_attr_possibilities(tag))
''')

write_file('/app/tornado_async_transformer/helpers.py', helpers_code)


# =============================================================================
# transformer.py — the main CSTTransformer implementation
# =============================================================================

transformer_code = textwrap.dedent('''\
    from typing import List, Optional, Set, Tuple, Union

    import libcst as cst
    from libcst import matchers as m

    from tornado_async_transformer.helpers import (
        name_attr_possibilities,
        some_version_of,
        with_added_imports,
    )


    # ---- matchers ----
    gen_return_statement_matcher = m.Raise(
        exc=some_version_of("tornado.gen.Return")
    )
    gen_return_call_with_args_matcher = m.Raise(
        exc=m.Call(
            func=some_version_of("tornado.gen.Return"),
            args=[m.AtLeastN(n=1)],
        )
    )
    gen_return_call_matcher = m.Raise(
        exc=m.Call(func=some_version_of("tornado.gen.Return"))
    )
    gen_return_matcher = gen_return_statement_matcher | gen_return_call_matcher
    gen_sleep_matcher = m.Call(func=some_version_of("gen.sleep"))
    gen_task_matcher = m.Call(func=some_version_of("gen.Task"))
    gen_coroutine_decorator_matcher = m.Decorator(
        decorator=some_version_of("tornado.gen.coroutine")
    )
    gen_test_coroutine_decorator = m.Decorator(
        decorator=some_version_of("tornado.testing.gen_test")
    )
    coroutine_decorator_matcher = (
        gen_coroutine_decorator_matcher | gen_test_coroutine_decorator
    )
    coroutine_matcher = m.FunctionDef(
        asynchronous=None,
        decorators=[m.ZeroOrMore(), coroutine_decorator_matcher, m.ZeroOrMore()],
    )


    class TransformError(Exception):
        """
        Error raised upon encountering a known error while attempting to
        transform the tree.
        """


    class TornadoAsyncTransformer(cst.CSTTransformer):
        """
        A libcst transformer that replaces the legacy @gen.coroutine/yield
        async syntax with the python3.7 native async/await syntax.

        This transformer doesn\'t remove any tornado imports from modified
        files.
        """

        def __init__(self) -> None:
            self.coroutine_stack: List[bool] = []
            self.required_imports: Set[str] = set()

        def leave_Module(
            self, node: cst.Module, updated_node: cst.Module
        ) -> cst.Module:
            if not self.required_imports:
                return updated_node

            imports = [
                self._make_simple_package_import(pkg)
                for pkg in self.required_imports
            ]
            return with_added_imports(updated_node, imports)

        def visit_Call(self, node: cst.Call) -> Optional[bool]:
            if m.matches(node, gen_task_matcher):
                raise TransformError(
                    "gen.Task "
                    "(https://www.tornadoweb.org/en/branch2.4/gen.html"
                    "#tornado.gen.Task) from tornado 2.4.1 is unsupported "
                    "by this codemod. This file has not been modified. "
                    "Manually update to supported syntax before running again."
                )
            return True

        def leave_Call(
            self, node: cst.Call, updated_node: cst.Call
        ) -> cst.Call:
            if not self._in_coroutine():
                return updated_node

            if m.matches(updated_node, gen_sleep_matcher):
                self.required_imports.add("asyncio")
                return updated_node.with_changes(
                    func=cst.Attribute(
                        value=cst.Name("asyncio"), attr=cst.Name("sleep")
                    )
                )

            return updated_node

        def visit_FunctionDef(self, node: cst.FunctionDef) -> Optional[bool]:
            self.coroutine_stack.append(m.matches(node, coroutine_matcher))
            return True

        def leave_FunctionDef(
            self, node: cst.FunctionDef, updated_node: cst.FunctionDef
        ) -> cst.FunctionDef:
            leaving_coroutine = self.coroutine_stack.pop()
            if not leaving_coroutine:
                return updated_node

            return updated_node.with_changes(
                decorators=[
                    decorator
                    for decorator in updated_node.decorators
                    if not m.matches(decorator, gen_coroutine_decorator_matcher)
                ],
                asynchronous=cst.Asynchronous(),
            )

        def leave_Raise(
            self, node: cst.Raise, updated_node: cst.Raise
        ) -> Union[cst.Return, cst.Raise]:
            if not self._in_coroutine():
                return updated_node

            if not m.matches(node, gen_return_matcher):
                return updated_node

            return_value, whitespace_after = self._pluck_gen_return_value(
                updated_node
            )
            return cst.Return(
                value=return_value,
                whitespace_after_return=whitespace_after,
                semicolon=updated_node.semicolon,
            )

        def leave_Yield(
            self, node: cst.Yield, updated_node: cst.Yield
        ) -> Union[cst.Await, cst.Yield]:
            if not self._in_coroutine():
                return updated_node

            if not isinstance(updated_node.value, cst.BaseExpression):
                return updated_node

            if isinstance(updated_node.value, (cst.List, cst.ListComp)):
                self.required_imports.add("asyncio")
                expression = self._make_asyncio_gather(updated_node)
            elif m.matches(
                updated_node,
                m.Yield(
                    value=(
                        (m.Dict() | m.DictComp())
                        | m.Call(func=m.Name("dict"))
                    )
                ),
            ):
                raise TransformError(
                    "Yielding a dict of futures "
                    "(https://www.tornadoweb.org/en/branch3.2/releases/"
                    "v3.2.0.html#tornado-gen) added in tornado 3.2 is "
                    "unsupported by the codemod. This file has not been "
                    "modified. Manually update to supported syntax before "
                    "running again."
                )
            else:
                expression = updated_node.value

            return cst.Await(
                expression=expression,
                whitespace_after_await=updated_node.whitespace_after_yield,
                lpar=updated_node.lpar,
                rpar=updated_node.rpar,
            )

        # ---- private helpers ----

        def _in_coroutine(self) -> bool:
            if not self.coroutine_stack:
                return False
            return self.coroutine_stack[-1]

        @staticmethod
        def _make_asyncio_gather(node: cst.Yield) -> cst.BaseExpression:
            return cst.Call(
                func=cst.Attribute(
                    value=cst.Name("asyncio"), attr=cst.Name("gather")
                ),
                args=[cst.Arg(value=node.value, star="*")],
            )

        @staticmethod
        def _pluck_gen_return_value(
            node: cst.Raise,
        ) -> Tuple[Optional[cst.BaseExpression], cst.SimpleWhitespace]:
            if m.matches(node, gen_return_call_with_args_matcher):
                return (
                    node.exc.args[0].value,
                    node.whitespace_after_raise,
                )
            return None, cst.SimpleWhitespace("")

        @staticmethod
        def _make_simple_package_import(package: str) -> cst.Import:
            assert "." not in package, (
                "this only supports a root package, e.g. \'import os\'"
            )
            return cst.Import(
                names=[cst.ImportAlias(name=cst.Name(package))]
            )
''')

write_file('/app/tornado_async_transformer/transformer.py', transformer_code)

print("Transformer implementation complete.")
