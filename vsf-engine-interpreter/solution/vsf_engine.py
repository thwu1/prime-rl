
"""
Validation Script Framework (VSF) Engine

Evaluates JSON payloads against declarative validation trees composed of
rule scripts with C#-like expression syntax, modeled on the NIST ESV
validation infrastructure.
"""

import json
import os
import re


class ValidationError:
    """Represents a single validation failure."""

    def __init__(self, property_path, rule_text):
        self.property_path = property_path
        self.rule_text = rule_text

    def __repr__(self):
        return f"ValidationError(path={self.property_path!r}, rule={self.rule_text!r})"


class ValidationResult:
    """Result of validating a payload against a tree."""

    def __init__(self, passed=True, errors=None):
        self.passed = passed
        self.errors = errors if errors is not None else []

    def __repr__(self):
        return f"ValidationResult(passed={self.passed}, errors={len(self.errors)})"


# ---------------------------------------------------------------------------
# Expression evaluator
# ---------------------------------------------------------------------------


class _StringStatic:
    """Proxy for C# string static methods."""
    pass


class _Int32Static:
    """Proxy for C# Int32 static methods."""
    pass


class _RegexStatic:
    """Proxy for C# Regex static methods."""
    pass


class ExpressionEvaluator:
    """Tokenises and evaluates C#-like rule expressions."""

    def __init__(self, current_property, parent_property, state=None):
        self.current_property = current_property
        self.parent_property = parent_property
        self.state = state or {}
        self._tokens = []
        self._pos = 0

    # -- tokeniser ----------------------------------------------------------

    @staticmethod
    def _tokenize(text):
        tokens = []
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]

            # whitespace
            if ch in " \t\r\n":
                i += 1
                continue

            # two-char operators
            if i + 1 < n:
                two = text[i : i + 2]
                if two in ("==", "!=", ">=", "<=", "&&", "||"):
                    tokens.append(two)
                    i += 2
                    continue

            # single-char delimiters / operators
            if ch in "().,!><":
                tokens.append(ch)
                i += 1
                continue

            # string literal
            if ch == '"':
                j = i + 1
                while j < n and text[j] != '"':
                    if text[j] == "\\":
                        j += 1
                    j += 1
                tokens.append(text[i : j + 1])
                i = j + 1
                continue

            # number (int or float)
            if ch.isdigit():
                j = i
                while j < n and (text[j].isdigit() or text[j] == "."):
                    j += 1
                tokens.append(text[i:j])
                i = j
                continue

            # identifier
            if ch.isalpha() or ch == "_":
                j = i
                while j < n and (text[j].isalnum() or text[j] == "_"):
                    j += 1
                tokens.append(text[i:j])
                i = j
                continue

            # skip unknown chars
            i += 1

        return tokens

    # -- recursive-descent parser -------------------------------------------

    def evaluate(self, expression):
        self._tokens = self._tokenize(expression)
        self._pos = 0
        result = self._parse_or()
        return result

    def _peek(self):
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return None

    def _consume(self):
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _expect(self, expected):
        tok = self._consume()
        if tok != expected:
            raise SyntaxError(f"Expected '{expected}', got '{tok}'")
        return tok

    def _parse_or(self):
        left = self._parse_and()
        while self._peek() == "||":
            self._consume()
            right = self._parse_and()
            left = left or right
        return left

    def _parse_and(self):
        left = self._parse_not()
        while self._peek() == "&&":
            self._consume()
            right = self._parse_not()
            left = left and right
        return left

    def _parse_not(self):
        if self._peek() == "!":
            self._consume()
            return not self._parse_not()
        return self._parse_comparison()

    def _parse_comparison(self):
        left = self._parse_primary()
        op = self._peek()
        if op in ("==", "!=", ">=", "<=", ">", "<"):
            self._consume()
            right = self._parse_primary()
            if op == "==":
                return left == right
            if op == "!=":
                return left != right
            if op == ">=":
                return left >= right
            if op == "<=":
                return left <= right
            if op == ">":
                return left > right
            if op == "<":
                return left < right
        return left

    def _parse_primary(self):
        tok = self._peek()
        if tok is None:
            raise SyntaxError("Unexpected end of expression")

        # parenthesised sub-expression
        if tok == "(":
            self._consume()
            val = self._parse_or()
            self._expect(")")
            return val

        # literals
        if tok == "null":
            self._consume()
            return None
        if tok == "true":
            self._consume()
            return True
        if tok == "false":
            self._consume()
            return False

        # string literal
        if tok.startswith('"'):
            self._consume()
            return tok[1:-1]

        # numeric literal
        if tok[0].isdigit():
            self._consume()
            return float(tok) if "." in tok else int(tok)

        # identifier (possibly chained property access / method calls)
        if tok[0].isalpha() or tok[0] == "_":
            return self._parse_chain()

        raise SyntaxError(f"Unexpected token: {tok}")

    def _parse_chain(self):
        """Parse an identifier with optional chained . access and method calls."""
        name = self._consume()
        value = self._resolve(name)

        while self._peek() == ".":
            self._consume()  # eat '.'
            member = self._consume()

            if self._peek() == "(":
                # method call
                self._consume()  # eat '('
                args = []
                if self._peek() != ")":
                    args.append(self._parse_or())
                    while self._peek() == ",":
                        self._consume()
                        args.append(self._parse_or())
                self._expect(")")
                value = self._call_method(value, member, args)
            else:
                # property access
                value = self._access_property(value, member)

        return value

    # -- helpers ------------------------------------------------------------

    def _resolve(self, name):
        if name == "currentProperty":
            return self.current_property
        if name == "parentProperty":
            return self.parent_property
        if name == "string":
            return _StringStatic()
        if name == "Int32":
            return _Int32Static()
        if name == "Regex":
            return _RegexStatic()
        if name in self.state:
            return self.state[name]
        raise NameError(f"Unknown identifier: {name}")

    @staticmethod
    def _access_property(obj, prop):
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(prop)
        if prop == "Length" and isinstance(obj, str):
            return len(obj)
        if hasattr(obj, prop):
            return getattr(obj, prop)
        raise AttributeError(f"Cannot access '{prop}' on {type(obj).__name__}")

    @staticmethod
    def _call_method(obj, method, args):
        # Static helpers
        if isinstance(obj, _StringStatic):
            if method == "IsNullOrWhiteSpace":
                val = args[0] if args else None
                if val is None:
                    return True
                return isinstance(val, str) and val.strip() == ""
            if method == "Format":
                fmt = args[0] if args else ""
                return fmt.format(*args[1:])
        if isinstance(obj, _Int32Static):
            if method == "Parse":
                return int(args[0])
        if isinstance(obj, _RegexStatic):
            if method == "IsMatch":
                return bool(re.search(args[1], args[0]))

        # List methods
        if isinstance(obj, list):
            if method == "Count":
                return len(obj)
            if method == "Distinct":
                seen = []
                for item in obj:
                    if item not in seen:
                        seen.append(item)
                return seen

        # String methods
        if isinstance(obj, str):
            if method == "StartsWith":
                return obj.startswith(args[0])
            if method == "Substring":
                return obj[int(args[0]) :]
            if method == "Length":
                return len(obj)

        # Nullable helpers
        if method == "GetValueOrDefault":
            return obj if obj is not None else (args[0] if args else 0)

        raise TypeError(f"Unknown method '{method}' on {type(obj).__name__}")


# ---------------------------------------------------------------------------
# Script executor
# ---------------------------------------------------------------------------

_RESULT_OK = "ok"
_RESULT_ERROR = "error"
_RESULT_EXIT = "exit"


class _ScriptRunner:
    """Executes VSF script lines in a given context."""

    def __init__(self, load_script_fn):
        self._load = load_script_fn

    def run_lines(self, lines, cur, par, path, errors, state):
        """Execute script lines sequentially with short-circuiting.

        Returns _RESULT_OK, _RESULT_ERROR, or _RESULT_EXIT.
        """
        for line in lines:
            lt = line.get("lineType", "")
            params = line.get("parameters", {})

            if lt == "Rule":
                res = self._handle_rule(line, cur, par, path, errors, state)
            elif lt == "ImportScript":
                res = self._handle_import(params, cur, par, path, errors, state)
            elif lt == "Branch":
                res = self._handle_branch(line, cur, par, path, errors, state)
            elif lt == "State":
                res = self._handle_state(params, cur, par, state)
            elif lt == "Assert":
                res = self._handle_assert(params, cur, par, state)
            elif lt == "Exit":
                return _RESULT_EXIT
            elif lt == "Information":
                continue
            else:
                continue  # unknown line type — skip

            if res == _RESULT_EXIT:
                return _RESULT_EXIT
            if res == _RESULT_ERROR:
                return _RESULT_ERROR

        return _RESULT_OK

    # -- individual line-type handlers --------------------------------------

    def _handle_rule(self, line, cur, par, path, errors, state):
        rule_type = line.get("ruleType", "")
        rule_text = line.get("parameters", {}).get("ruleText", "")

        try:
            ev = ExpressionEvaluator(cur, par, state)
            result = ev.evaluate(rule_text)
        except Exception:
            if rule_type == "External":
                errors.append(ValidationError(path, rule_text))
            return _RESULT_ERROR

        if not result:
            if rule_type == "External":
                errors.append(ValidationError(path, rule_text))
            return _RESULT_ERROR

        return _RESULT_OK

    def _handle_import(self, params, cur, par, path, errors, state):
        script_file = params.get("scriptFile", "")
        script = self._load(script_file)
        return self.run_lines(script.get("vsfScript", []), cur, par, path, errors, state)

    def _handle_branch(self, line, cur, par, path, errors, state):
        conditions = line.get("conditions", [])

        for cond_block in conditions:
            if "if" in cond_block or "elseif" in cond_block:
                key = "if" if "if" in cond_block else "elseif"
                cond_lines = cond_block[key].get("scriptLines", [])
                then_lines = cond_block.get("then", {}).get("scriptLines", [])

                # evaluate condition — errors are NOT collected
                cond_errors = []
                res = self.run_lines(
                    cond_lines, cur, par, path, cond_errors, dict(state)
                )

                if res not in (_RESULT_ERROR,) and len(cond_errors) == 0:
                    # condition met → execute then block (errors ARE collected)
                    return self.run_lines(then_lines, cur, par, path, errors, state)
                # condition not met → try next

            elif "else" in cond_block:
                else_lines = cond_block["else"].get("scriptLines", [])
                return self.run_lines(else_lines, cur, par, path, errors, state)

        return _RESULT_OK  # no branch matched

    def _handle_state(self, params, cur, par, state):
        key = params.get("key", "")
        value_expr = params.get("value", "")
        try:
            ev = ExpressionEvaluator(cur, par, state)
            state[key] = ev.evaluate(value_expr)
        except Exception:
            pass  # state failures are non-fatal and do not short-circuit
        return _RESULT_OK

    def _handle_assert(self, params, cur, par, state):
        rule_text = params.get("ruleText", "")
        try:
            ev = ExpressionEvaluator(cur, par, state)
            result = ev.evaluate(rule_text)
            if not result:
                return _RESULT_ERROR  # assert failure — stop, no validation error
        except Exception:
            return _RESULT_ERROR
        return _RESULT_OK


# ---------------------------------------------------------------------------
# Tree walker
# ---------------------------------------------------------------------------


class VsfEngine:
    """Validation Script Framework engine."""

    def __init__(self, rules_base_dir):
        self._rules_dir = rules_base_dir
        self._cache = {}

    # -- public API ---------------------------------------------------------

    def validate(self, tree_path, payload):
        with open(tree_path, "r") as f:
            tree_data = json.load(f)

        tree = tree_data[0]
        root = tree["rootNode"]

        errors = []
        self._walk_root(root, payload, errors)

        return ValidationResult(passed=len(errors) == 0, errors=errors)

    # -- script loading -----------------------------------------------------

    def _load_script(self, script_file):
        if script_file in self._cache:
            return self._cache[script_file]
        path = os.path.join(self._rules_dir, script_file)
        with open(path, "r") as f:
            data = json.load(f)
        self._cache[script_file] = data
        return data

    # -- tree traversal -----------------------------------------------------

    def _runner(self):
        return _ScriptRunner(self._load_script)

    def _exec_node_scripts(self, node_data, cur, par, path, errors):
        """Run a node's vsfScriptFiles list. Returns True if Exit triggered."""
        runner = self._runner()
        for sf in node_data.get("vsfScriptFiles", []):
            script_file = sf.get("scriptFile", "")
            break_on_error = sf.get("breakOnError", True)

            script = self._load_script(script_file)
            res = runner.run_lines(
                script.get("vsfScript", []), cur, par, path, errors, {}
            )

            if res == _RESULT_EXIT:
                return True

            if res == _RESULT_ERROR and break_on_error:
                break

        return False

    def _walk_root(self, root_node, payload, errors):
        # root-level scripts
        if "nodeData" in root_node:
            exited = self._exec_node_scripts(
                root_node["nodeData"], payload, None, "", errors
            )
            if exited:
                return

        # child nodes
        for child in root_node.get("nodes", []):
            self._walk_child(child, payload, "", errors)

    def _walk_child(self, node, parent_obj, parent_path, errors):
        node_type = node.get("nodeType", "leaf")
        prop_id = node.get("property", {}).get("internalIdentifier", "")
        current_path = f"{parent_path}.{prop_id}" if parent_path else prop_id

        # resolve current value from parent
        cur_val = None
        if isinstance(parent_obj, dict):
            cur_val = parent_obj.get(prop_id)

        if node_type == "leaf":
            self._walk_leaf(node, cur_val, parent_obj, current_path, errors)

        elif node_type == "parent":
            self._walk_parent(node, cur_val, parent_obj, current_path, errors)

        elif node_type == "list":
            self._walk_list(node, cur_val, parent_obj, current_path, errors)

    def _walk_leaf(self, node, cur_val, parent_obj, path, errors):
        if "nodeData" in node:
            self._exec_node_scripts(node["nodeData"], cur_val, parent_obj, path, errors)

    def _walk_parent(self, node, cur_val, parent_obj, path, errors):
        if "nodeData" in node:
            exited = self._exec_node_scripts(
                node["nodeData"], cur_val, parent_obj, path, errors
            )
            if exited:
                return

        for child in node.get("nodes", []):
            self._walk_child(child, cur_val, path, errors)

    def _walk_list(self, node, cur_val, parent_obj, path, errors):
        # list-level scripts
        if "nodeData" in node:
            exited = self._exec_node_scripts(
                node["nodeData"], cur_val, parent_obj, path, errors
            )
            if exited:
                return

        # iterate items
        if not isinstance(cur_val, list) or "listItem" not in node:
            return

        list_item = node["listItem"]
        branch_data = list_item.get("branchNodeData", {})

        for i, item in enumerate(cur_val):
            item_path = f"{path}[{i}]"

            # runBeforeListItem
            if "runBeforeListItem" in branch_data:
                self._exec_node_scripts(
                    branch_data["runBeforeListItem"], item, cur_val, item_path, errors
                )

            # list item child nodes
            for child in list_item.get("nodes", []):
                self._walk_child(child, item, item_path, errors)

            # runAfterListItem
            if "runAfterListItem" in branch_data:
                self._exec_node_scripts(
                    branch_data["runAfterListItem"], item, cur_val, item_path, errors
                )
