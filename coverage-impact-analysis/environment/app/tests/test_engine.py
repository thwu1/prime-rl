import pytest
from src.engine import RuleEngine


class TestRuleEngine:
    def test_add_and_evaluate_rules(self):
        engine = RuleEngine()
        engine.add_rule('r1', lambda c: c.get('x', 0) > 0, lambda c: c['x'] * 2)
        engine.add_rule('r2', lambda c: c.get('x', 0) < 0, lambda c: -c['x'], priority=1)
        results = engine.evaluate({'x': 5})
        assert results == [('r1', 10)]

    def test_stop_on_first(self):
        engine = RuleEngine()
        engine.add_rule('r1', lambda c: True, lambda c: 'first', priority=2)
        engine.add_rule('r2', lambda c: True, lambda c: 'second', priority=1)
        results = engine.evaluate({'stop_on_first': True})
        assert len(results) == 1
        assert results[0] == ('r1', 'first')

    def test_rule_error_strict(self):
        engine = RuleEngine()
        engine.add_rule('bad', lambda c: True, lambda c: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            engine.evaluate({'strict': True})

    def test_rule_error_lenient(self):
        engine = RuleEngine()
        engine.add_rule('bad', lambda c: True, lambda c: 1 / 0)
        results = engine.evaluate({})
        assert results == []
        assert engine.audit_log[-1]['status'] == 'error'

    def test_classify_negative_extreme(self):
        engine = RuleEngine()
        r = engine.classify(-200)
        assert r['category'] == 'negative'
        assert r['severity'] == 'extreme'

    def test_classify_negative_moderate(self):
        engine = RuleEngine()
        r = engine.classify(-50)
        assert r['category'] == 'negative'
        assert r['severity'] == 'moderate'

    def test_classify_negative_mild(self):
        engine = RuleEngine()
        r = engine.classify(-5)
        assert r['category'] == 'negative'
        assert r['severity'] == 'mild'

    def test_classify_zero(self):
        engine = RuleEngine()
        r = engine.classify(0)
        assert r['category'] == 'zero'
        assert r['severity'] == 'neutral'

    def test_classify_positive_extreme(self):
        engine = RuleEngine()
        r = engine.classify(200)
        assert r['category'] == 'positive'
        assert r['severity'] == 'extreme'

    def test_classify_text_short(self):
        engine = RuleEngine()
        r = engine.classify("hello")
        assert r['category'] == 'text'
        assert r['severity'] == 'short'

    def test_classify_text_long(self):
        engine = RuleEngine()
        r = engine.classify("x" * 100)
        assert r['category'] == 'text'
        assert r['severity'] == 'long'

    def test_classify_unknown(self):
        engine = RuleEngine()
        r = engine.classify([1, 2, 3])
        assert r['category'] == 'unknown'
        assert r['severity'] == 'undefined'
