"""
Tests for the GraphQL executor — verifies spec-compliant execution results.
"""

import json
import os
import subprocess
import tempfile

import pytest


def run_executor(schema: str, query: str, root_value: dict, variables: dict = None):
    """Execute a GraphQL query via the CLI and return the parsed ExecutionResult."""
    payload = {"schema": schema, "query": query, "rootValue": root_value}
    if variables is not None:
        payload["variables"] = variables

    fd, path = tempfile.mkstemp(suffix=".json", dir="/tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)

        proc = subprocess.run(
            ["npx", "tsx", "/app/src/cli.ts", path],
            capture_output=True,
            text=True,
            cwd="/app",
            timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"Executor exit {proc.returncode}\n"
                f"STDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
            )
        out = proc.stdout.strip()
        if not out:
            raise RuntimeError(f"Empty output. STDERR: {proc.stderr}")
        return json.loads(out)
    finally:
        os.unlink(path)


def run_executor_ts(ts_body: str):
    """Execute TypeScript code that imports executor directly (for function resolvers)."""
    ts_code = "import { executeGraphQL } from './src/executor';\n" + ts_body
    fd, fpath = tempfile.mkstemp(suffix=".ts", dir="/app")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(ts_code)

        proc = subprocess.run(
            ["npx", "tsx", fpath],
            capture_output=True,
            text=True,
            cwd="/app",
            timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"TS executor exit {proc.returncode}\n"
                f"STDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
            )
        out = proc.stdout.strip()
        if not out:
            raise RuntimeError(f"Empty output. STDERR: {proc.stderr}")
        return json.loads(out)
    finally:
        os.unlink(fpath)


# ──────────────────────────────────────────────────────────────
# Basic resolution (should pass with the starter code)
# ──────────────────────────────────────────────────────────────

class TestBasicResolution:
    def test_scalar_fields(self):
        r = run_executor(
            "type Query { hello: String, num: Int }",
            "{ hello num }",
            {"hello": "world", "num": 42},
        )
        assert r["data"] == {"hello": "world", "num": 42}
        assert "errors" not in r

    def test_nested_object(self):
        r = run_executor(
            "type Query { user: User } type User { name: String, age: Int }",
            "{ user { name age } }",
            {"user": {"name": "Alice", "age": 30}},
        )
        assert r["data"] == {"user": {"name": "Alice", "age": 30}}
        assert "errors" not in r

    def test_nullable_returns_null(self):
        r = run_executor(
            "type Query { name: String }",
            "{ name }",
            {"name": None},
        )
        assert r["data"] == {"name": None}
        assert "errors" not in r


# ──────────────────────────────────────────────────────────────
# Non-Null propagation
# ──────────────────────────────────────────────────────────────

class TestNonNullPropagation:
    def test_nonnull_bubbles_to_nullable_parent(self):
        r = run_executor(
            "type Query { nest: Nest } type Nest { value: String! }",
            "{ nest { value } }",
            {"nest": {"value": None}},
        )
        assert r["data"] == {"nest": None}
        errs = r.get("errors", [])
        assert len(errs) == 1
        assert errs[0]["path"] == ["nest", "value"]
        assert "Cannot return null" in errs[0]["message"]
        assert "Nest.value" in errs[0]["message"]

    def test_deep_nonnull_chain(self):
        schema = """
            type Query { a: A }
            type A { b: B! }
            type B { c: C! }
            type C { val: String! }
        """
        r = run_executor(schema, "{ a { b { c { val } } } }",
                         {"a": {"b": {"c": {"val": None}}}})
        assert r["data"] == {"a": None}
        errs = r.get("errors", [])
        assert len(errs) == 1
        assert errs[0]["path"] == ["a", "b", "c", "val"]

    def test_nonnull_root_becomes_null(self):
        r = run_executor(
            "type Query { value: String! }",
            "{ value }",
            {"value": None},
        )
        assert r["data"] is None
        errs = r.get("errors", [])
        assert len(errs) == 1
        assert errs[0]["path"] == ["value"]

    def test_nullable_sibling_survives(self):
        schema = "type Query { a: Obj, b: String } type Obj { x: String! }"
        r = run_executor(schema, "{ a { x } b }",
                         {"a": {"x": None}, "b": "ok"})
        assert r["data"] == {"a": None, "b": "ok"}
        errs = r.get("errors", [])
        assert len(errs) == 1
        assert errs[0]["path"] == ["a", "x"]


# ──────────────────────────────────────────────────────────────
# List completion
# ──────────────────────────────────────────────────────────────

class TestListCompletion:
    def test_nullable_list_elements(self):
        r = run_executor(
            "type Query { names: [String] }",
            "{ names }",
            {"names": ["Alice", None, "Charlie"]},
        )
        assert r["data"] == {"names": ["Alice", None, "Charlie"]}
        assert "errors" not in r

    def test_list_error_path_has_index(self):
        schema = "type Query { items: [Item] } type Item { name: String! }"
        r = run_executor(schema, "{ items { name } }",
                         {"items": [{"name": "ok"}, {"name": None}, {"name": "fine"}]})
        assert r["data"] == {"items": [{"name": "ok"}, None, {"name": "fine"}]}
        errs = r.get("errors", [])
        assert len(errs) == 1
        assert errs[0]["path"] == ["items", 1, "name"]

    def test_nonnull_element_nullifies_list(self):
        r = run_executor(
            "type Query { tags: [String!] }",
            "{ tags }",
            {"tags": ["a", None, "c"]},
        )
        assert r["data"] == {"tags": None}
        errs = r.get("errors", [])
        assert len(errs) == 1
        assert errs[0]["path"] == ["tags", 1]

    def test_nonnull_list_of_nonnull_elements(self):
        r = run_executor(
            "type Query { tags: [String!]! }",
            "{ tags }",
            {"tags": ["a", None, "c"]},
        )
        assert r["data"] is None
        errs = r.get("errors", [])
        assert len(errs) >= 1
        assert any(e["path"] == ["tags", 1] for e in errs)


# ──────────────────────────────────────────────────────────────
# Aliases
# ──────────────────────────────────────────────────────────────

class TestAliases:
    def test_simple_alias(self):
        r = run_executor(
            "type Query { name: String }",
            "{ myName: name }",
            {"name": "Alice"},
        )
        assert r["data"] == {"myName": "Alice"}
        assert "name" not in r["data"]

    def test_multiple_aliases_same_field(self):
        r = run_executor(
            "type Query { value: Int }",
            "{ a: value b: value c: value }",
            {"value": 42},
        )
        assert r["data"] == {"a": 42, "b": 42, "c": 42}

    def test_alias_in_error_path(self):
        r = run_executor(
            "type Query { item: Item } type Item { val: String! }",
            "{ thing: item { v: val } }",
            {"item": {"val": None}},
        )
        assert r["data"] == {"thing": None}
        errs = r.get("errors", [])
        assert len(errs) == 1
        assert errs[0]["path"] == ["thing", "v"]


# ──────────────────────────────────────────────────────────────
# Named fragments
# ──────────────────────────────────────────────────────────────

class TestFragments:
    def test_named_fragment(self):
        r = run_executor(
            "type Query { user: User } type User { name: String, email: String }",
            """
            query { user { ...UF } }
            fragment UF on User { name email }
            """,
            {"user": {"name": "Bob", "email": "bob@x.com"}},
        )
        assert r["data"] == {"user": {"name": "Bob", "email": "bob@x.com"}}

    def test_nested_named_fragments(self):
        schema = """
            type Query { user: User }
            type User { name: String, address: Address }
            type Address { city: String, country: String }
        """
        query = """
            query { user { ...UF } }
            fragment UF on User { name address { ...AF } }
            fragment AF on Address { city country }
        """
        r = run_executor(schema, query,
                         {"user": {"name": "Bob", "address": {"city": "NYC", "country": "US"}}})
        assert r["data"] == {
            "user": {"name": "Bob", "address": {"city": "NYC", "country": "US"}}
        }

    def test_fragment_on_interface(self):
        schema = """
            interface Animal { name: String }
            type Dog implements Animal { name: String, woofs: Boolean }
            type Query { pet: Animal }
        """
        query = """
            query { pet { ...AF ... on Dog { woofs } } }
            fragment AF on Animal { name }
        """
        r = run_executor(schema, query,
                         {"pet": {"__typename": "Dog", "name": "Rex", "woofs": True}})
        assert r["data"] == {"pet": {"name": "Rex", "woofs": True}}

    def test_fragment_not_applied_to_wrong_type(self):
        schema = """
            type Query { user: User }
            type User { name: String }
            type Admin { level: Int }
        """
        query = """
            query { user { name ...AdminF } }
            fragment AdminF on Admin { level }
        """
        r = run_executor(schema, query, {"user": {"name": "Alice"}})
        assert r["data"] == {"user": {"name": "Alice"}}
        assert "errors" not in r


# ──────────────────────────────────────────────────────────────
# Abstract types
# ──────────────────────────────────────────────────────────────

class TestAbstractTypes:
    def test_interface_inline_fragments(self):
        schema = """
            interface Animal { name: String }
            type Dog implements Animal { name: String, woofs: Boolean }
            type Cat implements Animal { name: String, meows: Boolean }
            type Query { pets: [Animal] }
        """
        r = run_executor(schema,
                         "{ pets { name ... on Dog { woofs } ... on Cat { meows } } }",
                         {"pets": [
                             {"__typename": "Dog", "name": "Rex", "woofs": True},
                             {"__typename": "Cat", "name": "Whiskers", "meows": True},
                         ]})
        assert r["data"] == {
            "pets": [{"name": "Rex", "woofs": True},
                     {"name": "Whiskers", "meows": True}]
        }

    def test_union_inline_fragments(self):
        schema = """
            union Result = User | Post
            type User { name: String }
            type Post { title: String }
            type Query { search: [Result] }
        """
        r = run_executor(schema,
                         "{ search { ... on User { name } ... on Post { title } } }",
                         {"search": [
                             {"__typename": "User", "name": "Alice"},
                             {"__typename": "Post", "title": "Hello"},
                         ]})
        assert r["data"] == {
            "search": [{"name": "Alice"}, {"title": "Hello"}]
        }

    def test_union_type_condition_in_fragment(self):
        """Inline fragment whose type condition is a union type."""
        schema = """
            interface Node { id: String }
            union Entity = Article | Comment
            type Article implements Node { id: String, title: String }
            type Comment implements Node { id: String, body: String }
            type Query { nodes: [Node] }
        """
        query = """
        {
            nodes {
                id
                ... on Entity {
                    ... on Article { title }
                    ... on Comment { body }
                }
            }
        }
        """
        r = run_executor(schema, query, {
            "nodes": [
                {"__typename": "Article", "id": "1", "title": "First"},
                {"__typename": "Comment", "id": "2", "body": "Nice!"},
            ]
        })
        assert r["data"] == {
            "nodes": [
                {"id": "1", "title": "First"},
                {"id": "2", "body": "Nice!"},
            ]
        }


# ──────────────────────────────────────────────────────────────
# @skip and @include directives
# ──────────────────────────────────────────────────────────────

class TestDirectives:
    def test_include_literal_true(self):
        """@include(if: true) should include the field."""
        r = run_executor(
            "type Query { a: String, b: String }",
            "{ a @include(if: true) b }",
            {"a": "hello", "b": "world"},
        )
        assert r["data"] == {"a": "hello", "b": "world"}
        assert "errors" not in r

    def test_include_literal_false(self):
        """@include(if: false) should exclude the field."""
        r = run_executor(
            "type Query { a: String, b: String }",
            "{ a @include(if: false) b }",
            {"a": "hello", "b": "world"},
        )
        assert r["data"] == {"b": "world"}
        assert "errors" not in r

    def test_skip_with_variable_false(self):
        """@skip(if: $cond) with $cond=false should include the field."""
        r = run_executor(
            "type Query { a: String, b: String }",
            "query($cond: Boolean!) { a @skip(if: $cond) b }",
            {"a": "hello", "b": "world"},
            variables={"cond": False},
        )
        assert r["data"] == {"a": "hello", "b": "world"}
        assert "errors" not in r

    def test_include_with_variable_true(self):
        """@include(if: $show) with $show=true should include the field."""
        r = run_executor(
            "type Query { a: String, b: String }",
            "query($show: Boolean!) { a @include(if: $show) b }",
            {"a": "hello", "b": "world"},
            variables={"show": True},
        )
        assert r["data"] == {"a": "hello", "b": "world"}
        assert "errors" not in r

    def test_include_with_variable_false(self):
        """@include(if: $show) with $show=false should exclude the field."""
        r = run_executor(
            "type Query { a: String, b: String }",
            "query($show: Boolean!) { a @include(if: $show) b }",
            {"a": "hello", "b": "world"},
            variables={"show": False},
        )
        assert r["data"] == {"b": "world"}
        assert "errors" not in r

    def test_include_on_inline_fragment(self):
        """@include on inline fragment controls fragment inclusion."""
        schema = """
            interface Animal { name: String }
            type Dog implements Animal { name: String, breed: String }
            type Query { pet: Animal }
        """
        r = run_executor(schema,
            "{ pet { name ... on Dog @include(if: true) { breed } } }",
            {"pet": {"__typename": "Dog", "name": "Rex", "breed": "Labrador"}},
        )
        assert r["data"] == {"pet": {"name": "Rex", "breed": "Labrador"}}

    def test_skip_on_fragment_spread(self):
        """@skip on a named fragment spread with variable."""
        r = run_executor(
            "type Query { user: User } type User { name: String, age: Int }",
            """
            query($hide: Boolean!) {
                user { name ...Details @skip(if: $hide) }
            }
            fragment Details on User { age }
            """,
            {"user": {"name": "Alice", "age": 30}},
            variables={"hide": True},
        )
        assert r["data"] == {"user": {"name": "Alice"}}
        assert "errors" not in r

    def test_skip_and_include_both_present(self):
        """@skip(if: true) takes precedence even when @include(if: true)."""
        r = run_executor(
            "type Query { a: String, b: String }",
            "{ a @skip(if: true) @include(if: true) b }",
            {"a": "hello", "b": "world"},
        )
        assert r["data"] == {"b": "world"}
        assert "errors" not in r


# ──────────────────────────────────────────────────────────────
# Variable default values
# ──────────────────────────────────────────────────────────────

class TestVariableDefaults:
    def test_default_true_skip(self):
        """@skip with variable default true and variable not provided."""
        r = run_executor(
            "type Query { a: String, b: String }",
            "query($hide: Boolean = true) { a @skip(if: $hide) b }",
            {"a": "hello", "b": "world"},
            variables={},
        )
        assert r["data"] == {"b": "world"}
        assert "errors" not in r

    def test_default_true_include(self):
        """@include with variable default true and variable not provided."""
        r = run_executor(
            "type Query { a: String, b: String }",
            "query($show: Boolean = true) { a @include(if: $show) b }",
            {"a": "hello", "b": "world"},
            variables={},
        )
        assert r["data"] == {"a": "hello", "b": "world"}
        assert "errors" not in r

    def test_default_overridden_by_provided(self):
        """Explicitly provided variable overrides default value."""
        r = run_executor(
            "type Query { a: String, b: String }",
            "query($hide: Boolean = true) { a @skip(if: $hide) b }",
            {"a": "hello", "b": "world"},
            variables={"hide": False},
        )
        assert r["data"] == {"a": "hello", "b": "world"}
        assert "errors" not in r

    def test_multiple_variable_defaults(self):
        """Multiple variables with different default values."""
        r = run_executor(
            "type Query { a: String, b: String, c: String }",
            "query($skipA: Boolean = true, $showC: Boolean = true) { a @skip(if: $skipA) b c @include(if: $showC) }",
            {"a": "hello", "b": "world", "c": "!"},
            variables={},
        )
        assert r["data"] == {"b": "world", "c": "!"}
        assert "errors" not in r

    def test_default_on_fragment_spread(self):
        """@skip on fragment spread with variable default true."""
        r = run_executor(
            "type Query { user: User } type User { name: String, age: Int }",
            """
            query($hideAge: Boolean = true) {
                user { name ...AgeFrag @skip(if: $hideAge) }
            }
            fragment AgeFrag on User { age }
            """,
            {"user": {"name": "Alice", "age": 30}},
            variables={},
        )
        assert r["data"] == {"user": {"name": "Alice"}}
        assert "errors" not in r


# ──────────────────────────────────────────────────────────────
# Scalar type serialization
# ──────────────────────────────────────────────────────────────

class TestScalarSerialization:
    def test_string_from_number(self):
        """Numeric value for String field must serialize to string."""
        r = run_executor(
            "type Query { label: String }",
            "{ label }",
            {"label": 42},
        )
        assert r["data"]["label"] == "42"
        assert isinstance(r["data"]["label"], str)
        assert "errors" not in r

    def test_boolean_from_one(self):
        """Numeric 1 for Boolean field must serialize to true."""
        r = run_executor(
            "type Query { flag: Boolean }",
            "{ flag }",
            {"flag": 1},
        )
        assert r["data"]["flag"] is True
        assert "errors" not in r

    def test_float_from_string(self):
        """String numeric for Float field must serialize to number."""
        r = run_executor(
            "type Query { rate: Float }",
            "{ rate }",
            {"rate": "3.14"},
        )
        assert r["data"]["rate"] == 3.14
        assert isinstance(r["data"]["rate"], float)
        assert "errors" not in r

    def test_int_from_string(self):
        """String numeric for Int field must serialize to integer."""
        r = run_executor(
            "type Query { count: Int }",
            "{ count }",
            {"count": "42"},
        )
        assert r["data"]["count"] == 42
        assert isinstance(r["data"]["count"], int)
        assert "errors" not in r

    def test_id_from_number(self):
        """Numeric value for ID field must serialize to string."""
        r = run_executor(
            "type Query { code: ID }",
            "{ code }",
            {"code": 123},
        )
        assert r["data"]["code"] == "123"
        assert isinstance(r["data"]["code"], str)
        assert "errors" not in r


# ──────────────────────────────────────────────────────────────
# Falsy value integrity
# ──────────────────────────────────────────────────────────────

class TestFalsyValues:
    def test_zero_int(self):
        """Integer zero must resolve as 0, not null."""
        r = run_executor(
            "type Query { count: Int }",
            "{ count }",
            {"count": 0},
        )
        assert r["data"]["count"] == 0
        assert r["data"]["count"] is not None
        assert "errors" not in r

    def test_false_boolean(self):
        """Boolean false must resolve as false, not null."""
        r = run_executor(
            "type Query { active: Boolean }",
            "{ active }",
            {"active": False},
        )
        assert r["data"]["active"] is False
        assert "errors" not in r

    def test_empty_string(self):
        """Empty string must resolve as '', not null."""
        r = run_executor(
            "type Query { label: String }",
            "{ label }",
            {"label": ""},
        )
        assert r["data"]["label"] == ""
        assert r["data"]["label"] is not None
        assert "errors" not in r

    def test_zero_nonnull_int(self):
        """NonNull Int with value 0 must not trigger null propagation."""
        r = run_executor(
            "type Query { count: Int! }",
            "{ count }",
            {"count": 0},
        )
        assert r["data"] == {"count": 0}
        assert "errors" not in r

    def test_falsy_fields_in_list_objects(self):
        """Falsy values in object fields within a list must be preserved."""
        schema = "type Query { items: [Item] } type Item { count: Int, active: Boolean }"
        r = run_executor(schema, "{ items { count active } }",
                         {"items": [
                             {"count": 0, "active": False},
                             {"count": 5, "active": True},
                         ]})
        assert r["data"] == {"items": [
            {"count": 0, "active": False},
            {"count": 5, "active": True},
        ]}
        # Strict type checks for falsy values
        assert r["data"]["items"][0]["count"] is not None
        assert r["data"]["items"][0]["active"] is False
        assert "errors" not in r


# ──────────────────────────────────────────────────────────────
# Field argument resolution (function resolvers)
# ──────────────────────────────────────────────────────────────

class TestFieldArguments:
    def test_literal_argument(self):
        """Field argument with literal string value invokes function resolver."""
        r = run_executor_ts('''
const r = executeGraphQL(
    `type Query { greet(name: String!): String }`,
    '{ greet(name: "World") }',
    { greet: (args: any) => "Hello, " + args.name + "!" },
);
process.stdout.write(JSON.stringify(r));
''')
        assert r["data"] == {"greet": "Hello, World!"}
        assert "errors" not in r

    def test_argument_with_variable(self):
        """Variable reference in field argument resolved from variables map."""
        r = run_executor_ts('''
const r = executeGraphQL(
    `type Query { greet(name: String!): String }`,
    'query($n: String!) { greet(name: $n) }',
    { greet: (args: any) => "Hello, " + args.name + "!" },
    { n: "TypeScript" },
);
process.stdout.write(JSON.stringify(r));
''')
        assert r["data"] == {"greet": "Hello, TypeScript!"}
        assert "errors" not in r

    def test_argument_default_from_schema(self):
        """Schema-defined argument default value applied when omitted from query."""
        r = run_executor_ts('''
const r = executeGraphQL(
    `type Query { greet(name: String = "World"): String }`,
    '{ greet }',
    { greet: (args: any) => "Hi, " + args.name + "!" },
);
process.stdout.write(JSON.stringify(r));
''')
        assert r["data"] == {"greet": "Hi, World!"}
        assert "errors" not in r

    def test_argument_overrides_schema_default(self):
        """Explicit query argument overrides schema-defined default value."""
        r = run_executor_ts('''
const r = executeGraphQL(
    `type Query { greet(name: String = "World"): String }`,
    '{ greet(name: "Alice") }',
    { greet: (args: any) => "Hi, " + args.name + "!" },
);
process.stdout.write(JSON.stringify(r));
''')
        assert r["data"] == {"greet": "Hi, Alice!"}
        assert "errors" not in r

    def test_function_resolver_with_serialization(self):
        """Function resolver returning number for String field requires scalar serialization."""
        r = run_executor_ts('''
const r = executeGraphQL(
    `type Query { label(id: Int!): String }`,
    '{ label(id: 42) }',
    { label: (args: any) => args.id },
);
process.stdout.write(JSON.stringify(r));
''')
        assert r["data"]["label"] == "42"
        assert isinstance(r["data"]["label"], str)
        assert "errors" not in r

    def test_function_resolver_with_alias(self):
        """Function resolver result uses alias as response key."""
        r = run_executor_ts('''
const r = executeGraphQL(
    `type Query { compute(x: Int!): Int }`,
    '{ result: compute(x: 5) }',
    { compute: (args: any) => args.x * 2 },
);
process.stdout.write(JSON.stringify(r));
''')
        assert r["data"] == {"result": 10}
        assert "compute" not in r["data"]
        assert "errors" not in r

    def test_function_resolver_nonnull_returns_null(self):
        """Function resolver returning null for NonNull field triggers error + null propagation."""
        r = run_executor_ts('''
const r = executeGraphQL(
    `type Query { wrapper: Wrapper }
     type Wrapper { required(key: String!): String! }`,
    '{ wrapper { required(key: "missing") } }',
    { wrapper: { required: (_args: any) => null } },
);
process.stdout.write(JSON.stringify(r));
''')
        assert r["data"] == {"wrapper": None}
        errs = r.get("errors", [])
        assert len(errs) == 1
        assert errs[0]["path"] == ["wrapper", "required"]
        assert "Wrapper.required" in errs[0]["message"]

    def test_multiple_arguments(self):
        """Field with multiple arguments passes all to resolver."""
        r = run_executor_ts('''
const r = executeGraphQL(
    `type Query { add(a: Int!, b: Int!): Int }`,
    '{ add(a: 3, b: 7) }',
    { add: (args: any) => args.a + args.b },
);
process.stdout.write(JSON.stringify(r));
''')
        assert r["data"] == {"add": 10}
        assert "errors" not in r

    def test_argument_with_operation_variable_default(self):
        """Argument uses variable whose default comes from operation definition.
        Requires variable default processing, variable resolution, argument extraction,
        and function resolver invocation."""
        r = run_executor_ts('''
const r = executeGraphQL(
    `type Query { greet(name: String!): String }`,
    'query($n: String = "Default") { greet(name: $n) }',
    { greet: (args: any) => "Hello, " + args.name + "!" },
    {},
);
process.stdout.write(JSON.stringify(r));
''')
        assert r["data"] == {"greet": "Hello, Default!"}
        assert "errors" not in r

    def test_plain_value_unaffected_by_arguments(self):
        """Non-function source values are returned directly, arguments ignored."""
        r = run_executor_ts('''
const r = executeGraphQL(
    `type Query { value(unused: Int): String }`,
    '{ value(unused: 99) }',
    { value: "plain" },
);
process.stdout.write(JSON.stringify(r));
''')
        assert r["data"] == {"value": "plain"}
        assert "errors" not in r


# ──────────────────────────────────────────────────────────────
# Combined: all features interacting (bugs 1-10, JSON tests)
# ──────────────────────────────────────────────────────────────

class TestCombined:
    def test_all_core_features(self):
        """Exercises null-bubbling, list indices, aliases, named fragments,
        and union type conditions together in one query."""
        schema = """
            interface Node { id: String }
            union Searchable = Article | Comment
            type Article implements Node {
                id: String
                title: String!
                author: Author
            }
            type Comment implements Node {
                id: String
                body: String
            }
            type Author { name: String! }
            type Query { results: [Node] }
        """
        query = """
            query {
                items: results {
                    ...NodeInfo
                    ... on Searchable {
                        ... on Article {
                            headline: title
                            author { authorName: name }
                        }
                        ... on Comment { text: body }
                    }
                }
            }
            fragment NodeInfo on Node { nodeId: id }
        """
        root = {
            "results": [
                {"__typename": "Article", "id": "1", "title": "GraphQL Guide",
                 "author": {"name": None}},
                {"__typename": "Comment", "id": "2", "body": "Great!"},
                {"__typename": "Article", "id": "3", "title": "TS Tips",
                 "author": {"name": "Bob"}},
            ]
        }

        r = run_executor(schema, query, root)

        expected = {
            "items": [
                {"nodeId": "1", "headline": "GraphQL Guide", "author": None},
                {"nodeId": "2", "text": "Great!"},
                {"nodeId": "3", "headline": "TS Tips",
                 "author": {"authorName": "Bob"}},
            ]
        }
        assert r["data"] == expected

        errs = r.get("errors", [])
        assert len(errs) == 1
        assert errs[0]["path"] == ["items", 0, "author", "authorName"]
        assert "Author.name" in errs[0]["message"]

    def test_all_features_with_directives(self):
        """Exercises all feature areas with explicitly provided variables."""
        schema = """
            interface Node { id: String }
            union Searchable = Article | Comment
            type Article implements Node {
                id: String
                title: String!
                author: Author
            }
            type Comment implements Node {
                id: String
                body: String
            }
            type Author { name: String! }
            type Query { results: [Node] }
        """
        query = """
            query($showDetails: Boolean!, $hideIds: Boolean!) {
                items: results {
                    ...NodeInfo @skip(if: $hideIds)
                    ... on Searchable @include(if: $showDetails) {
                        ... on Article {
                            headline: title
                            author { authorName: name }
                        }
                        ... on Comment { text: body }
                    }
                }
            }
            fragment NodeInfo on Node { nodeId: id }
        """
        root = {
            "results": [
                {"__typename": "Article", "id": "1", "title": "GraphQL Guide",
                 "author": {"name": None}},
                {"__typename": "Comment", "id": "2", "body": "Great!"},
                {"__typename": "Article", "id": "3", "title": "TS Tips",
                 "author": {"name": "Bob"}},
            ]
        }

        r = run_executor(schema, query, root,
                         variables={"showDetails": True, "hideIds": False})

        expected = {
            "items": [
                {"nodeId": "1", "headline": "GraphQL Guide", "author": None},
                {"nodeId": "2", "text": "Great!"},
                {"nodeId": "3", "headline": "TS Tips",
                 "author": {"authorName": "Bob"}},
            ]
        }
        assert r["data"] == expected

        errs = r.get("errors", [])
        assert len(errs) == 1
        assert errs[0]["path"] == ["items", 0, "author", "authorName"]
        assert "Author.name" in errs[0]["message"]

    def test_all_features_with_defaults(self):
        """Exercises bugs 1-8: null-bubbling, list indices, aliases,
        named fragments, union types, variable resolution,
        @include/@skip directives, and variable default values."""
        schema = """
            interface Node { id: String }
            union Searchable = Article | Comment
            type Article implements Node {
                id: String
                title: String!
                author: Author
            }
            type Comment implements Node {
                id: String
                body: String
            }
            type Author { name: String! }
            type Query { results: [Node] }
        """
        query = """
            query($showDetails: Boolean = true, $hideIds: Boolean = false) {
                items: results {
                    ...NodeInfo @skip(if: $hideIds)
                    ... on Searchable @include(if: $showDetails) {
                        ... on Article {
                            headline: title
                            author { authorName: name }
                        }
                        ... on Comment { text: body }
                    }
                }
            }
            fragment NodeInfo on Node { nodeId: id }
        """
        root = {
            "results": [
                {"__typename": "Article", "id": "1", "title": "GraphQL Guide",
                 "author": {"name": None}},
                {"__typename": "Comment", "id": "2", "body": "Great!"},
                {"__typename": "Article", "id": "3", "title": "TS Tips",
                 "author": {"name": "Bob"}},
            ]
        }

        r = run_executor(schema, query, root, variables={})

        expected = {
            "items": [
                {"nodeId": "1", "headline": "GraphQL Guide", "author": None},
                {"nodeId": "2", "text": "Great!"},
                {"nodeId": "3", "headline": "TS Tips",
                 "author": {"authorName": "Bob"}},
            ]
        }
        assert r["data"] == expected

        errs = r.get("errors", [])
        assert len(errs) == 1
        assert errs[0]["path"] == ["items", 0, "author", "authorName"]
        assert "Author.name" in errs[0]["message"]


# ──────────────────────────────────────────────────────────────
# Cascading: interactions requiring multiple bug fixes
# ──────────────────────────────────────────────────────────────

class TestCascading:
    def test_boolean_zero_requires_serialize_and_falsy(self):
        """Boolean field with numeric 0: needs falsy fix (||->??) AND serialize.
        Without falsy fix: 0->null. Without serialize: 0 stays 0 (not false)."""
        r = run_executor(
            "type Query { flag: Boolean }",
            "{ flag }",
            {"flag": 0},
        )
        assert r["data"]["flag"] is False
        assert "errors" not in r

    def test_alias_with_serialization(self):
        """String field with alias and numeric value needing coercion.
        Requires alias fix AND serialize fix."""
        r = run_executor(
            "type Query { value: String }",
            "{ label: value }",
            {"value": 42},
        )
        assert r["data"] == {"label": "42"}
        assert "label" in r["data"]
        assert "value" not in r["data"]
        assert "errors" not in r

    def test_nonnull_serialized_in_list_with_path(self):
        """List with NonNull String field receiving numeric values.
        Requires NonNull throw + list path + serialize."""
        schema = "type Query { items: [Item] } type Item { tag: String! }"
        r = run_executor(schema, "{ items { tag } }",
                         {"items": [{"tag": 42}, {"tag": None}, {"tag": 99}]})
        # First and third items serialize number->string; second is null->NonNull error
        assert r["data"]["items"][0] == {"tag": "42"}
        assert r["data"]["items"][1] is None
        assert r["data"]["items"][2] == {"tag": "99"}
        errs = r.get("errors", [])
        assert len(errs) == 1
        assert errs[0]["path"] == ["items", 1, "tag"]

    def test_all_ten_bugs_json(self):
        """Comprehensive test exercising bugs 1-10 via JSON CLI:
        NonNull propagation, list paths, aliases, named fragments, union types,
        variable resolution, directives, variable defaults, scalar serialization,
        and falsy value integrity."""
        schema = """
            interface Node { id: String }
            union SearchResult = Article | Review
            type Article implements Node {
                id: String
                title: String!
                views: Int
            }
            type Review implements Node {
                id: String
                rating: Boolean
            }
            type Query { results: [Node] }
        """
        query = """
            query($showDetails: Boolean = true, $hideIds: Boolean = false) {
                entries: results {
                    ...NodeId @skip(if: $hideIds)
                    ... on SearchResult @include(if: $showDetails) {
                        ... on Article {
                            headline: title
                            viewCount: views
                        }
                        ... on Review {
                            liked: rating
                        }
                    }
                }
            }
            fragment NodeId on Node { nodeId: id }
        """
        root = {
            "results": [
                {"__typename": "Article", "id": "1", "title": "GraphQL",
                 "views": 0},
                {"__typename": "Review", "id": "2", "rating": 1},
                {"__typename": "Article", "id": "3", "title": None,
                 "views": 100},
            ]
        }

        r = run_executor(schema, query, root, variables={})

        expected_data = {
            "entries": [
                {"nodeId": "1", "headline": "GraphQL", "viewCount": 0},
                {"nodeId": "2", "liked": True},
                None,
            ]
        }
        assert r["data"] == expected_data

        # Strict type checks for serialized/falsy values
        assert r["data"]["entries"][0]["viewCount"] == 0
        assert r["data"]["entries"][0]["viewCount"] is not None
        assert r["data"]["entries"][1]["liked"] is True

        errs = r.get("errors", [])
        assert len(errs) == 1
        assert errs[0]["path"] == ["entries", 2, "headline"]
        assert "Article.title" in errs[0]["message"]

    def test_args_with_directive_and_variable_default(self):
        """Function resolver with arguments, @include directive, and variable default.
        Requires fixes 7, 8, 11, 12."""
        r = run_executor_ts('''
const r = executeGraphQL(
    `type Query { a: String, greet(name: String!): String }`,
    `query($show: Boolean = true, $name: String!) {
        a @include(if: $show)
        greet(name: $name)
    }`,
    {
        a: "visible",
        greet: (args: any) => "Hello, " + args.name + "!",
    },
    { name: "World" },
);
process.stdout.write(JSON.stringify(r));
''')
        assert r["data"] == {"a": "visible", "greet": "Hello, World!"}
        assert "errors" not in r

    def test_function_resolver_falsy_return(self):
        """Function resolver returning 0 for Int field must not become null.
        Requires fixes 10, 11, 12."""
        r = run_executor_ts('''
const r = executeGraphQL(
    `type Query { score(base: Int!): Int }`,
    '{ score(base: 0) }',
    { score: (args: any) => args.base },
);
process.stdout.write(JSON.stringify(r));
''')
        assert r["data"]["score"] == 0
        assert r["data"]["score"] is not None
        assert "errors" not in r

    def test_all_twelve_bugs(self):
        """Comprehensive test exercising all 12 bug areas simultaneously:
        NonNull propagation, list paths, aliases, named fragments, union types,
        variable resolution, directives, variable defaults, scalar serialization,
        falsy value integrity, argument extraction, and function resolvers."""
        r = run_executor_ts('''
const schema = `
    interface Node { id: String }
    union SearchResult = Article | Review
    type Article implements Node {
        id: String
        title: String!
        views: Int
        formatted(prefix: String = "Article"): String
    }
    type Review implements Node {
        id: String
        rating: Boolean
        summary(maxLen: Int!): String
    }
    type Query { results: [Node] }
`;
const query = `
    query($showDetails: Boolean = true, $hideIds: Boolean = false) {
        entries: results {
            ...NodeId @skip(if: $hideIds)
            ... on SearchResult @include(if: $showDetails) {
                ... on Article {
                    headline: title
                    viewCount: views
                    label: formatted(prefix: "Post")
                }
                ... on Review {
                    liked: rating
                    brief: summary(maxLen: 100)
                }
            }
        }
    }
    fragment NodeId on Node { nodeId: id }
`;
const root = {
    results: [
        {
            __typename: "Article", id: "1", title: "GraphQL",
            views: 0,
            formatted: (args: any) => args.prefix + ": GraphQL",
        },
        {
            __typename: "Review", id: "2", rating: 1,
            summary: (args: any) => "Great content (max " + args.maxLen + ")",
        },
        {
            __typename: "Article", id: "3", title: null,
            views: 100,
            formatted: (args: any) => args.prefix + ": null",
        },
    ],
};
const r = executeGraphQL(schema, query, root, {});
process.stdout.write(JSON.stringify(r));
''')
        expected = {
            "entries": [
                {"nodeId": "1", "headline": "GraphQL", "viewCount": 0,
                 "label": "Post: GraphQL"},
                {"nodeId": "2", "liked": True,
                 "brief": "Great content (max 100)"},
                None,
            ]
        }
        assert r["data"] == expected

        # Strict type checks
        assert r["data"]["entries"][0]["viewCount"] == 0
        assert r["data"]["entries"][0]["viewCount"] is not None
        assert r["data"]["entries"][1]["liked"] is True
        assert isinstance(r["data"]["entries"][0]["label"], str)
        assert isinstance(r["data"]["entries"][1]["brief"], str)

        errs = r.get("errors", [])
        assert len(errs) == 1
        assert errs[0]["path"] == ["entries", 2, "headline"]
        assert "Article.title" in errs[0]["message"]
