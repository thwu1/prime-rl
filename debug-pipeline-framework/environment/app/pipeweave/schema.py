"""Schema validation and coercion for data records.

A schema is a dict mapping field names to specification dicts::

    {
        'field': {
            'type': 'string' | 'int' | 'float' | 'bool' | 'list',
            'required': bool,
            'default': <value>,
            'pattern': <regex>,
            'min': <number>,
            'max': <number>,
            'choices': [<values>],
            'coerce': bool,
        }
    }
"""
import re
from collections import OrderedDict


class ValidationError(Exception):
    def __init__(self, message, field=None, errors=None):
        super().__init__(message)
        self.field = field
        self.errors = errors or []


class SchemaValidator:
    """Validates (and optionally coerces) records against a schema."""

    def __init__(self, schema):
        self.schema = OrderedDict(schema)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_record(self, record, coerce=True):
        """Validate a single record.

        Returns ``(validated_record, errors)`` where *errors* is a
        list of human-readable strings (empty when the record is valid).
        When *coerce* is True, values are coerced to their declared type
        before validation.
        """
        errors = []
        result = OrderedDict()

        for field_name, spec in self.schema.items():
            value = record.get(field_name)

            # --- Missing field handling ---
            if value is None and field_name not in record:
                if spec.get('required', False):
                    if 'default' in spec:
                        result[field_name] = spec['default']
                    else:
                        errors.append(
                            f"Missing required field: {field_name}"
                        )
                elif 'default' in spec:
                    continue
                else:
                    continue
            elif value is None:
                # Present but None
                if spec.get('required', False) and 'default' not in spec:
                    errors.append(f"Field '{field_name}' cannot be None")
                    continue
                elif 'default' in spec:
                    result[field_name] = spec['default']
                else:
                    result[field_name] = None
                continue
            else:
                # --- Value is present; coerce then validate ---
                if coerce and spec.get('coerce', True):
                    value, cerr = self._coerce_value(value, spec['type'])
                    if cerr:
                        errors.append(f"Field '{field_name}': {cerr}")
                        continue

                if not self._check_type(value, spec['type']):
                    errors.append(
                        f"Field '{field_name}' expected type "
                        f"{spec['type']}, got {type(value).__name__}"
                    )
                    continue

                pat = spec.get('pattern')
                if pat and isinstance(value, str):
                    if not re.match(pat, value):
                        errors.append(
                            f"Field '{field_name}' does not match "
                            f"pattern: {pat}"
                        )
                        continue

                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    lo = spec.get('min')
                    hi = spec.get('max')
                    if lo is not None and value < lo:
                        errors.append(
                            f"Field '{field_name}' value {value} "
                            f"below minimum {lo}"
                        )
                        continue
                    if hi is not None and value > hi:
                        errors.append(
                            f"Field '{field_name}' value {value} "
                            f"above maximum {hi}"
                        )
                        continue

                choices = spec.get('choices')
                if choices and value not in choices:
                    errors.append(
                        f"Field '{field_name}' value '{value}' "
                        f"not in allowed choices: {choices}"
                    )
                    continue

                result[field_name] = value

        # Pass through fields not declared in schema
        for key, val in record.items():
            if key not in self.schema and key not in result:
                result[key] = val

        return dict(result), errors

    def validate_records(self, records, coerce=True):
        """Validate a list of records.

        Returns ``(validated_records, all_errors)``.
        """
        validated = []
        all_errors = []
        for i, record in enumerate(records):
            res, errs = self.validate_record(record, coerce=coerce)
            validated.append(res)
            for e in errs:
                all_errors.append(f"Record {i}: {e}")
        return validated, all_errors

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _coerce_value(self, value, target_type):
        """Return ``(coerced, error_or_None)``."""
        try:
            if target_type == 'string':
                return str(value), None
            elif target_type == 'int':
                return int(value), None
            elif target_type == 'float':
                return float(value), None
            elif target_type == 'bool':
                if isinstance(value, str):
                    if value.lower() in ('true', '1', 'yes', 'on'):
                        return True, None
                    elif value.lower() in ('false', '0', 'no', 'off'):
                        return False, None
                    return None, f"Cannot coerce '{value}' to bool"
                return bool(value), None
            elif target_type == 'list':
                if isinstance(value, str):
                    return [v.strip() for v in value.split(',')], None
                if isinstance(value, (list, tuple)):
                    return list(value), None
                return [value], None
            return value, f"Unknown type: {target_type}"
        except (ValueError, TypeError) as e:
            return None, str(e)

    def _check_type(self, value, expected_type):
        type_map = {
            'string': str,
            'int': int,
            'float': (int, float),
            'bool': bool,
            'list': (list, tuple),
        }
        expected = type_map.get(expected_type)
        if expected is None:
            return True
        if expected_type == 'int' and isinstance(value, bool):
            return False
        return isinstance(value, expected)
