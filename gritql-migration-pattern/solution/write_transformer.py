#!/usr/bin/env python3
"""Generate the complete restlib-to-httpclient transformer implementation.

"""


TRANSFORMER_CODE = r'''"""Format-preserving code migration transformer: restlib -> httpclient.

Uses libcst (concrete syntax tree) to transform Python source code that
uses the ``restlib`` HTTP library into equivalent code using ``httpclient``,
preserving all formatting, comments, and string literals.
"""

import libcst as cst
import libcst.matchers as m

EXCEPTION_MAP = {
    "RequestError": "TransportError",
    "ConnectionError": "ConnectError",
    "Timeout": "TimeoutError",
    "HTTPError": "HTTPStatusError",
}

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}


class RestlibToHttpclientTransformer(cst.CSTTransformer):
    """CSTTransformer that rewrites restlib API usage to httpclient."""

    def __init__(self):
        super().__init__()
        self._bare_renames: dict[str, str] = {}

    # ------------------------------------------------------------------ #
    # import restlib  ->  import httpclient
    # ------------------------------------------------------------------ #
    def leave_Import(self, original_node, updated_node):
        if isinstance(updated_node.names, cst.ImportStar):
            return updated_node
        new_names = []
        changed = False
        for alias in updated_node.names:
            if m.matches(alias, m.ImportAlias(name=m.Name(value="restlib"))):
                new_names.append(alias.with_changes(name=cst.Name("httpclient")))
                changed = True
            else:
                new_names.append(alias)
        if changed:
            return updated_node.with_changes(names=new_names)
        return updated_node

    # ------------------------------------------------------------------ #
    # from restlib import Session  ->  from httpclient import Client
    # from restlib.exceptions import X  ->  from httpclient.errors import Y
    # ------------------------------------------------------------------ #
    def leave_ImportFrom(self, original_node, updated_node):
        module = updated_node.module
        if module is None or isinstance(updated_node.names, cst.ImportStar):
            return updated_node

        # from restlib import Session  ->  from httpclient import Client
        if m.matches(module, m.Name(value="restlib")):
            new_names = []
            changed = False
            for alias in updated_node.names:
                if m.matches(alias, m.ImportAlias(name=m.Name(value="Session"))):
                    new_names.append(alias.with_changes(name=cst.Name("Client")))
                    self._bare_renames["Session"] = "Client"
                    changed = True
                else:
                    new_names.append(alias)
            if changed:
                return updated_node.with_changes(
                    module=cst.Name("httpclient"),
                    names=new_names,
                )
            return updated_node

        # from restlib.exceptions import X  ->  from httpclient.errors import Y
        if m.matches(
            module,
            m.Attribute(value=m.Name(value="restlib"), attr=m.Name(value="exceptions")),
        ):
            new_names = []
            for alias in updated_node.names:
                if isinstance(alias.name, cst.Name) and alias.name.value in EXCEPTION_MAP:
                    old_name = alias.name.value
                    new_name = EXCEPTION_MAP[old_name]
                    new_names.append(alias.with_changes(name=cst.Name(new_name)))
                    self._bare_renames[old_name] = new_name
                else:
                    new_names.append(alias)
            return updated_node.with_changes(
                module=cst.Attribute(
                    value=cst.Name("httpclient"),
                    attr=cst.Name("errors"),
                ),
                names=new_names,
            )

        return updated_node

    # ------------------------------------------------------------------ #
    # restlib.exceptions.X  ->  httpclient.mapped(X)
    # ONLY exception patterns - method attributes are handled in leave_Call
    # ------------------------------------------------------------------ #
    def leave_Attribute(self, original_node, updated_node):
        # restlib.exceptions.<exc>  ->  httpclient.<mapped_exc>
        if (
            m.matches(
                updated_node.value,
                m.Attribute(
                    value=m.Name(value="restlib"), attr=m.Name(value="exceptions")
                ),
            )
            and isinstance(updated_node.attr, cst.Name)
            and updated_node.attr.value in EXCEPTION_MAP
        ):
            return updated_node.with_changes(
                value=cst.Name("httpclient"),
                attr=cst.Name(EXCEPTION_MAP[updated_node.attr.value]),
            )

        # Do NOT transform restlib.get, restlib.post, etc. here.
        # Those are handled in leave_Call where argument restructuring
        # can be applied together with the function rename.
        return updated_node

    # ------------------------------------------------------------------ #
    # Call transformations: method calls, Session, retry decorator
    # ------------------------------------------------------------------ #
    def leave_Call(self, original_node, updated_node):
        func = updated_node.func
        if not m.matches(func, m.Attribute(value=m.Name(value="restlib"))):
            return updated_node

        method_name = func.attr.value

        # restlib.get/post/put/delete/patch -> httpclient.fetch("METHOD", ...)
        if method_name in HTTP_METHODS:
            method_str = method_name.upper()
            new_args = self._insert_method_arg(method_str, updated_node.args)
            new_args = self._rename_kwarg(new_args, "data", "content")
            return updated_node.with_changes(
                func=func.with_changes(
                    value=cst.Name("httpclient"),
                    attr=cst.Name("fetch"),
                ),
                args=new_args,
            )

        # restlib.Session(...) -> httpclient.Client(...)
        if method_name == "Session":
            new_args = self._convert_timeout_ms(updated_node.args)
            return updated_node.with_changes(
                func=func.with_changes(
                    value=cst.Name("httpclient"),
                    attr=cst.Name("Client"),
                ),
                args=new_args,
            )

        # restlib.retry(...) -> httpclient.with_retry(...)
        if method_name == "retry":
            new_args = self._transform_retry_args(updated_node.args)
            return updated_node.with_changes(
                func=func.with_changes(
                    value=cst.Name("httpclient"),
                    attr=cst.Name("with_retry"),
                ),
                args=new_args,
            )

        return updated_node

    # ------------------------------------------------------------------ #
    # Bare-name renames (from from-import rewrites)
    # ------------------------------------------------------------------ #
    def leave_Name(self, original_node, updated_node):
        if updated_node.value in self._bare_renames:
            return updated_node.with_changes(
                value=self._bare_renames[updated_node.value]
            )
        return updated_node

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _insert_method_arg(method_str, args):
        """Insert the HTTP method string as the first positional argument."""
        method_arg = cst.Arg(
            value=cst.SimpleString('"' + method_str + '"'),
            comma=cst.Comma(whitespace_after=cst.SimpleWhitespace(" ")),
        )
        return (method_arg,) + tuple(args)

    @staticmethod
    def _rename_kwarg(args, old_name, new_name):
        """Rename a keyword argument."""
        new_args = []
        for arg in args:
            if arg.keyword is not None and arg.keyword.value == old_name:
                new_args.append(arg.with_changes(keyword=cst.Name(new_name)))
            else:
                new_args.append(arg)
        return tuple(new_args)

    @staticmethod
    def _convert_timeout_ms(args):
        """Convert timeout_ms=N kwarg to timeout=N/1000 as float."""
        new_args = []
        for arg in args:
            if (arg.keyword is not None
                    and arg.keyword.value == "timeout_ms"
                    and isinstance(arg.value, cst.Integer)):
                ms_val = int(arg.value.value)
                sec_val = ms_val / 1000
                new_args.append(arg.with_changes(
                    keyword=cst.Name("timeout"),
                    value=cst.Float(str(sec_val)),
                ))
            else:
                new_args.append(arg)
        return tuple(new_args)

    @staticmethod
    def _transform_retry_args(args):
        """Transform retry decorator arguments:
        max_retries=N -> attempts=N+1, delay=D -> backoff=float(D)."""
        new_args = []
        for arg in args:
            if arg.keyword is not None:
                if (arg.keyword.value == "max_retries"
                        and isinstance(arg.value, cst.Integer)):
                    retries = int(arg.value.value)
                    new_args.append(arg.with_changes(
                        keyword=cst.Name("attempts"),
                        value=cst.Integer(str(retries + 1)),
                    ))
                elif (arg.keyword.value == "delay"
                      and isinstance(arg.value, cst.Integer)):
                    delay_val = float(int(arg.value.value))
                    new_args.append(arg.with_changes(
                        keyword=cst.Name("backoff"),
                        value=cst.Float(str(delay_val)),
                    ))
                else:
                    new_args.append(arg)
            else:
                new_args.append(arg)
        return tuple(new_args)


def transform(source: str) -> str:
    """Apply the restlib->httpclient migration to a source code string."""
    tree = cst.parse_module(source)
    transformer = RestlibToHttpclientTransformer()
    modified = tree.visit(transformer)
    return modified.code
'''


def main():
    output_path = "/app/transformer.py"
    with open(output_path, "w") as fh:
        fh.write(TRANSFORMER_CODE)
    print(f"Transformer written to {output_path}")


if __name__ == "__main__":
    main()
