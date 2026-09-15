"""Rule engine with classification logic."""


class RuleEngine:
    """A rule-based evaluation engine with value classification."""

    def __init__(self):
        self.rules = []
        self.audit_log = []

    def add_rule(self, name, condition, action, priority=0):
        """Register a named rule with a condition, action, and priority."""
        self.rules.append({
            'name': name,
            'condition': condition,
            'action': action,
            'priority': priority,
        })

    def evaluate(self, context):
        """Evaluate all rules against the given context dict.

        Rules are evaluated in descending priority order. If
        context['stop_on_first'] is truthy, evaluation halts after
        the first matching rule. If context['strict'] is truthy,
        exceptions in rule actions propagate; otherwise they are
        logged and swallowed.
        """
        results = []
        sorted_rules = sorted(
            self.rules, key=lambda r: r['priority'], reverse=True,
        )

        for rule in sorted_rules:
            try:
                if rule['condition'](context):
                    result = rule['action'](context)
                    results.append((rule['name'], result))
                    self.audit_log.append({
                        'rule': rule['name'],
                        'result': result,
                        'status': 'applied',
                    })
                    if context.get('stop_on_first'):
                        break
                else:
                    self.audit_log.append({
                        'rule': rule['name'],
                        'status': 'skipped',
                    })
            except Exception as e:
                self.audit_log.append({
                    'rule': rule['name'],
                    'status': 'error',
                    'error': str(e),
                })
                if context.get('strict'):
                    raise

        return results

    def classify(self, value):
        """Classify a value into category and severity buckets.

        Numeric values are classified by sign and magnitude.
        Strings are classified by length.  Other types return
        category='unknown'.
        """
        if isinstance(value, (int, float)):
            if value < 0:
                category = 'negative'
                if value < -100:
                    severity = 'extreme'
                elif value < -10:
                    severity = 'moderate'
                else:
                    severity = 'mild'
            elif value == 0:
                category = 'zero'
                severity = 'neutral'
            else:
                category = 'positive'
                if value > 100:
                    severity = 'extreme'
                elif value > 10:
                    severity = 'moderate'
                else:
                    severity = 'mild'
        elif isinstance(value, str):
            category = 'text'
            severity = 'long' if len(value) > 50 else 'short'
        else:
            category = 'unknown'
            severity = 'undefined'

        return {'category': category, 'severity': severity}
