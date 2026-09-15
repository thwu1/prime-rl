#!/usr/bin/env python3
"""
ESV Payload Validation Engine

Validates entropy source registration payloads against a JSON-driven
validation framework based on the NIST ESVTS protocol.

The engine loads validation tree configurations and rule scripts from
/app/config/ and applies them to JSON payloads.
"""

import json
import sys
import os
import re


CONFIG_DIR = "/app/config"
RULE_SCRIPTS_DIR = os.path.join(CONFIG_DIR, "rule_scripts")
VALIDATION_TREES_DIR = os.path.join(CONFIG_DIR, "validation_trees")


class PropertyWrapper:
    """Wraps Python values for C#-like property access in expression evaluation.

    Enables dot-notation attribute access on dicts, and provides Length,
    Count(), and Trim() methods/properties matching the C# expression syntax
    used in rule scripts.
    """

    def __init__(self, data):
        object.__setattr__(self, '_data', data)

    def _raw(self):
        return object.__getattribute__(self, '_data')

    def __getattr__(self, name):
        if name == '_data':
            return object.__getattribute__(self, '_data')
        data = self._raw()
        if isinstance(data, dict):
            val = data.get(name)
            return PropertyWrapper(val)
        if name == 'Length':
            if isinstance(data, (str, list)):
                return len(data)
            raise AttributeError(f"Cannot access Length on {type(data).__name__}")
        return PropertyWrapper(None)

    def Count(self):
        data = self._raw()
        if data is not None and hasattr(data, '__len__'):
            return len(data)
        raise TypeError(f"Cannot Count() on {type(data).__name__}")

    def Trim(self):
        data = self._raw()
        if isinstance(data, str):
            return PropertyWrapper(data.strip())
        raise TypeError(f"Cannot Trim() on {type(data).__name__}")

    def strip(self):
        data = self._raw()
        if isinstance(data, str):
            return data.strip()
        raise TypeError(f"Cannot strip() on {type(data).__name__}")

    def __eq__(self, other):
        data = self._raw()
        if isinstance(other, PropertyWrapper):
            other = other._raw()
        return data == other

    def __ne__(self, other):
        return not self.__eq__(other)

    def __lt__(self, other):
        data = self._raw()
        if isinstance(other, PropertyWrapper):
            other = other._raw()
        return data < other

    def __le__(self, other):
        data = self._raw()
        if isinstance(other, PropertyWrapper):
            other = other._raw()
        return data <= other

    def __gt__(self, other):
        data = self._raw()
        if isinstance(other, PropertyWrapper):
            other = other._raw()
        return data > other

    def __ge__(self, other):
        data = self._raw()
        if isinstance(other, PropertyWrapper):
            other = other._raw()
        return data >= other

    def __bool__(self):
        data = self._raw()
        if data is None:
            return False
        return bool(data)

    def __repr__(self):
        return f"PW({self._raw()!r})"

    def __hash__(self):
        data = self._raw()
        if isinstance(data, (list, dict)):
            return id(data)
        return hash(data)


class ValidationError:
    """Represents a single validation error."""

    def __init__(self, path, message, script_file=None):
        self.path = path
        self.message = message
        self.script_file = script_file

    def to_dict(self):
        result = {"path": self.path, "message": self.message}
        if self.script_file:
            result["scriptFile"] = self.script_file
        return result


class ValidationResult:
    """Accumulates validation errors and determines overall validity."""

    def __init__(self):
        self.errors = []

    @property
    def valid(self):
        return len(self.errors) == 0

    def add_error(self, path, message, script_file=None):
        self.errors.append(ValidationError(path, message, script_file))

    def to_dict(self):
        return {
            "valid": self.valid,
            "errors": [e.to_dict() for e in self.errors]
        }


class ExpressionEvaluator:
    """Evaluates C#-like expressions by transforming them to Python and using eval."""

    def evaluate(self, expression, context):
        py_expr = self._transform(expression)
        namespace = dict(context)
        namespace['__builtins__'] = {}
        namespace['len'] = len
        try:
            return eval(py_expr, namespace)
        except Exception as e:
            raise ValueError(
                f"Expression evaluation failed: '{expression}' -> '{py_expr}': {e}"
            )

    def _transform(self, expr):
        """Transform C#-like syntax to Python equivalent."""
        expr = expr.replace('&&', ' and ')
        expr = expr.replace('||', ' or ')
        expr = re.sub(r'\bnull\b', 'None', expr)
        expr = re.sub(r'\btrue\b', 'True', expr)
        expr = re.sub(r'\bfalse\b', 'False', expr)
        return expr


class ScriptExecutor:
    """Loads and executes validation rule scripts."""

    def __init__(self, rules_dir, evaluator):
        self.rules_dir = rules_dir
        self.evaluator = evaluator
        self._cache = {}

    def _load(self, script_file):
        if script_file in self._cache:
            return self._cache[script_file]
        path = os.path.join(self.rules_dir, script_file)
        with open(path) as f:
            script = json.load(f)
        self._cache[script_file] = script
        return script

    def execute_script(self, script_file, context, result, path_prefix):
        """Execute a rule script. Returns True if all rules passed."""
        script = self._load(script_file)
        lines = script.get("vsfScript", [])
        return self._execute_lines(lines, context, result, path_prefix, script_file)

    def _execute_lines(self, lines, context, result, path_prefix, script_file=None):
        """Execute an array of script lines. Returns True if all passed."""
        for line in lines:
            lt = line.get("lineType", "")
            params = line.get("parameters", {})
            desc = line.get("description", "")

            if lt == "ImportScript":
                sf = params.get("scriptFile", "")
                if not self.execute_script(sf, context, result, path_prefix):
                    return False

            elif lt == "Rule":
                rule_text = params.get("ruleText", "")
                try:
                    if not self.evaluator.evaluate(rule_text, context):
                        msg = desc if desc else f"Rule failed: {rule_text}"
                        result.add_error(path_prefix, msg, script_file)
                        return False
                except Exception as e:
                    result.add_error(path_prefix, str(e), script_file)
                    return False

            elif lt == "Assert":
                rule_text = params.get("ruleText", "")
                try:
                    if not self.evaluator.evaluate(rule_text, context):
                        msg = desc if desc else f"Assertion failed: {rule_text}"
                        result.add_error(path_prefix, msg, script_file)
                        return False
                except Exception as e:
                    result.add_error(path_prefix, str(e), script_file)
                    return False

            elif lt == "State":
                key = params.get("key", "")
                value_expr = params.get("value", "")
                try:
                    context[key] = self.evaluator.evaluate(value_expr, context)
                except Exception as e:
                    result.add_error(path_prefix, str(e), script_file)
                    return False

            elif lt == "Branch":
                if not self._execute_branch(line, context, result, path_prefix, script_file):
                    return False

            elif lt == "Information":
                pass

        return True

    def _execute_branch(self, branch_line, context, result, path_prefix, script_file):
        """Execute a Branch line type with if/elseif/else conditions.

        The if/elseif condition blocks contain scriptLines that are executed
        as a boolean test. If all lines succeed (no errors), the condition
        is considered met and the then block is executed.
        """
        conditions = branch_line.get("conditions", [])

        for cond in conditions:
            if "if" in cond:
                if_lines = cond["if"].get("scriptLines", [])
                temp = ValidationResult()
                met = self._execute_lines(
                    if_lines, dict(context), temp, path_prefix, script_file
                )
                if met:
                    then_lines = cond.get("then", {}).get("scriptLines", [])
                    return self._execute_lines(
                        then_lines, context, result, path_prefix, script_file
                    )

            elif "elseif" in cond:
                elif_lines = cond["elseif"].get("scriptLines", [])
                temp = ValidationResult()
                met = self._execute_lines(
                    elif_lines, dict(context), temp, path_prefix, script_file
                )
                if met:
                    then_lines = cond.get("then", {}).get("scriptLines", [])
                    return self._execute_lines(
                        then_lines, context, result, path_prefix, script_file
                    )

            elif "else" in cond:
                else_lines = cond["else"].get("scriptLines", [])
                return self._execute_lines(
                    else_lines, context, result, path_prefix, script_file
                )

        return True


class TreeWalker:
    """Walks validation trees and applies rules to payload fields."""

    def __init__(self, executor):
        self.executor = executor

    def validate(self, tree, payload, result):
        """Validate a payload against a validation tree."""
        root = tree[0] if isinstance(tree, list) else tree
        root_node = root.get("rootNode", {})

        wrapped = PropertyWrapper(payload)
        context = {
            "currentProperty": wrapped,
            "parentProperty": PropertyWrapper(None),
        }

        node_data = root_node.get("nodeData", {})
        for sr in node_data.get("vsfScriptFiles", []):
            if not self.executor.execute_script(
                sr["scriptFile"], context, result, "$"
            ):
                return

        self._process_nodes(root_node.get("nodes", []), payload, None, result, "$")

    def _process_nodes(self, nodes, current_obj, parent_obj, result, path_prefix):
        """Process a list of node definitions against the current object."""
        for node in nodes:
            nt = node.get("nodeType", "")
            prop = node.get("property", {})
            ident = prop.get("internalIdentifier", "")
            field_path = f"{path_prefix}.{ident}" if path_prefix else ident

            if nt == "leaf":
                self._do_leaf(node, current_obj, result, field_path, ident)
            elif nt == "list":
                self._do_list(node, current_obj, result, field_path, ident)
            elif nt == "parent":
                self._do_parent(node, current_obj, result, field_path, ident)

    def _do_leaf(self, node, current_obj, result, field_path, ident):
        """Process a leaf node: extract value and run scripts."""
        value = current_obj.get(ident) if isinstance(current_obj, dict) else None
        ctx = {
            "currentProperty": PropertyWrapper(value),
            "parentProperty": PropertyWrapper(current_obj)
            if isinstance(current_obj, dict)
            else PropertyWrapper(None),
        }
        for sr in node.get("nodeData", {}).get("vsfScriptFiles", []):
            brk = sr.get("breakOnError", True)
            ok = self.executor.execute_script(sr["scriptFile"], ctx, result, field_path)
            if not ok and brk:
                break

    def _do_list(self, node, current_obj, result, field_path, ident):
        """Process a list node: validate list then iterate items with hooks."""
        list_val = current_obj.get(ident) if isinstance(current_obj, dict) else None
        parent_w = (
            PropertyWrapper(current_obj)
            if isinstance(current_obj, dict)
            else PropertyWrapper(None)
        )

        ctx = {"currentProperty": PropertyWrapper(list_val), "parentProperty": parent_w}
        for sr in node.get("nodeData", {}).get("vsfScriptFiles", []):
            if not self.executor.execute_script(
                sr["scriptFile"], ctx, result, field_path
            ):
                return

        if list_val is None:
            return

        li_cfg = node.get("listItem", {})
        bnd = li_cfg.get("branchNodeData", {})
        item_nodes = li_cfg.get("nodes", [])

        for idx, item in enumerate(list_val):
            ip = f"{field_path}[{idx}]"
            item_w = PropertyWrapper(item)

            # runBeforeListItem
            before = bnd.get("runBeforeListItem", {})
            bctx = {"currentProperty": item_w, "parentProperty": parent_w}
            before_ok = True
            for sr in before.get("vsfScriptFiles", []):
                if not self.executor.execute_script(
                    sr["scriptFile"], bctx, result, ip
                ):
                    before_ok = False
                    break
            if not before_ok:
                continue

            # Process child nodes of this list item
            if isinstance(item, dict):
                self._process_nodes(item_nodes, item, current_obj, result, ip)

            # runAfterListItem
            after = bnd.get("runAfterListItem", {})
            actx = {"currentProperty": item_w, "parentProperty": parent_w}
            for sr in after.get("vsfScriptFiles", []):
                self.executor.execute_script(sr["scriptFile"], actx, result, ip)

    def _do_parent(self, node, current_obj, result, field_path, ident):
        """Process a parent (nested object) node."""
        value = current_obj.get(ident) if isinstance(current_obj, dict) else None
        parent_w = (
            PropertyWrapper(current_obj)
            if isinstance(current_obj, dict)
            else PropertyWrapper(None)
        )
        ctx = {
            "currentProperty": PropertyWrapper(value),
            "parentProperty": parent_w,
        }
        for sr in node.get("nodeData", {}).get("vsfScriptFiles", []):
            if not self.executor.execute_script(
                sr["scriptFile"], ctx, result, field_path
            ):
                return
        if value is not None and isinstance(value, dict):
            self._process_nodes(
                node.get("nodes", []), value, current_obj, result, field_path
            )


def main():
    if len(sys.argv) < 2:
        print(
            json.dumps(
                {
                    "valid": False,
                    "errors": [
                        {"path": "", "message": "No payload file specified"}
                    ],
                }
            )
        )
        sys.exit(1)

    payload_file = sys.argv[1]
    tree_name = sys.argv[2] if len(sys.argv) > 2 else "registerEntropySource"

    with open(payload_file) as f:
        payload = json.load(f)

    tree_path = os.path.join(VALIDATION_TREES_DIR, f"{tree_name}.json")
    with open(tree_path) as f:
        tree = json.load(f)

    evaluator = ExpressionEvaluator()
    executor = ScriptExecutor(RULE_SCRIPTS_DIR, evaluator)
    walker = TreeWalker(executor)

    result = ValidationResult()
    walker.validate(tree, payload, result)

    print(json.dumps(result.to_dict(), indent=2))
    sys.exit(0 if result.valid else 1)


if __name__ == "__main__":
    main()
