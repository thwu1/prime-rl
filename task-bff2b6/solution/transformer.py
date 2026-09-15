from typing import List, Optional, Set, Tuple, Union

import libcst as cst
from libcst import matchers as m

from tornado_async_transformer.helpers import (
    some_version_of,
    with_added_imports,
)


# --- Matchers ---

# gen.Return variants
gen_return_statement_matcher = m.Raise(exc=some_version_of("tornado.gen.Return"))
gen_return_call_with_args_matcher = m.Raise(
    exc=m.Call(func=some_version_of("tornado.gen.Return"), args=[m.AtLeastN(n=1)])
)
gen_return_call_matcher = m.Raise(
    exc=m.Call(func=some_version_of("tornado.gen.Return"))
)
gen_return_matcher = gen_return_statement_matcher | gen_return_call_matcher

# gen.sleep / gen.Task / gen.moment
gen_sleep_matcher = m.Call(func=some_version_of("tornado.gen.sleep"))
gen_task_matcher = m.Call(func=some_version_of("tornado.gen.Task"))
gen_moment_matcher = some_version_of("tornado.gen.moment")

# Decorator matchers
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
    Error raised upon encountering a known unsupported pattern while
    attempting to transform the tree.
    """


class TornadoAsyncTransformer(cst.CSTTransformer):
    """
    A LibCST transformer that replaces Tornado's legacy @gen.coroutine/yield
    async syntax with Python's native async/await syntax.
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
                "gen.Task (https://www.tornadoweb.org/en/branch2.4/gen.html"
                "#tornado.gen.Task) from tornado 2.4.1 is unsupported by this "
                "codemod. This file has not been modified. Manually update to "
                "supported syntax before running again."
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

        # gen.moment sentinel -> asyncio.sleep(0)
        if m.matches(updated_node.value, gen_moment_matcher):
            self.required_imports.add("asyncio")
            expression = cst.Call(
                func=cst.Attribute(
                    value=cst.Name("asyncio"), attr=cst.Name("sleep")
                ),
                args=[cst.Arg(value=cst.Integer("0"))],
            )

        # List / ListComp / Tuple of futures -> asyncio.gather(*)
        elif isinstance(updated_node.value, (cst.List, cst.ListComp, cst.Tuple)):
            self.required_imports.add("asyncio")
            expression = cst.Call(
                func=cst.Attribute(
                    value=cst.Name("asyncio"), attr=cst.Name("gather")
                ),
                args=[cst.Arg(value=updated_node.value, star="*")],
            )

        # Dict / DictComp / dict() / Set / SetComp -> unsupported
        elif m.matches(
            updated_node,
            m.Yield(
                value=(
                    m.Dict()
                    | m.DictComp()
                    | m.Set()
                    | m.SetComp()
                    | m.Call(func=m.Name("dict"))
                )
            ),
        ):
            if isinstance(updated_node.value, (cst.Set, cst.SetComp)):
                raise TransformError(
                    "Yielding a set of futures is unsupported by this codemod. "
                    "This file has not been modified. Manually update to "
                    "supported syntax before running again."
                )
            raise TransformError(
                "Yielding a dict of futures "
                "(https://www.tornadoweb.org/en/branch3.2/releases/v3.2.0.html"
                "#tornado-gen) added in tornado 3.2 is unsupported by the "
                "codemod. This file has not been modified. Manually update to "
                "supported syntax before running again."
            )

        else:
            expression = updated_node.value

        return cst.Await(
            expression=expression,
            whitespace_after_await=updated_node.whitespace_after_yield,
            lpar=updated_node.lpar,
            rpar=updated_node.rpar,
        )

    def _in_coroutine(self) -> bool:
        if not self.coroutine_stack:
            return False
        return self.coroutine_stack[-1]

    @staticmethod
    def _pluck_gen_return_value(
        node: cst.Raise,
    ) -> Tuple[Optional[cst.BaseExpression], cst.SimpleWhitespace]:
        if m.matches(node, gen_return_call_with_args_matcher):
            return node.exc.args[0].value, node.whitespace_after_raise

        # No return value: don't preserve whitespace after 'raise'
        return None, cst.SimpleWhitespace("")

    @staticmethod
    def _make_simple_package_import(package: str) -> cst.Import:
        return cst.Import(
            names=[cst.ImportAlias(name=cst.Name(package))]
        )
