import sys
sys.path.insert(0, '/app')

import os
import re
import pytest



class TestInterpArithmetic:
    """Basic arithmetic and primitive operations."""

    def test_addition(self):
        from interp import run
        assert run("(+ 3 4)") == 7

    def test_subtraction(self):
        from interp import run
        assert run("(- 10 3)") == 7

    def test_multiplication(self):
        from interp import run
        assert run("(* 6 7)") == 42

    def test_comparison_true(self):
        from interp import run
        assert run("(= 5 5)") is True

    def test_comparison_false(self):
        from interp import run
        assert run("(= 5 3)") is False


class TestInterpBinding:
    """Let bindings and variable scoping."""

    def test_let_simple(self):
        from interp import run
        assert run("(let ((x 10)) (+ x 1))") == 11

    def test_nested_let(self):
        from interp import run
        result = run("""
            (let ((x 5))
              (let ((y 10))
                (+ x y)))
        """)
        assert result == 15

    def test_let_shadow(self):
        from interp import run
        result = run("""
            (let ((x 1))
              (let ((x 2))
                x))
        """)
        assert result == 2


class TestInterpFunctions:
    """Lambda, closures, and higher-order functions."""

    def test_lambda_application(self):
        from interp import run
        result = run("""
            (let ((f (lambda (x) (+ x 1))))
              (f 10))
        """)
        assert result == 11

    def test_higher_order(self):
        from interp import run
        result = run("""
            (let ((apply (lambda (f x) (f x))))
              (let ((inc (lambda (y) (+ y 1))))
                (apply inc 5)))
        """)
        assert result == 6

    def test_closure_free_vars(self):
        from interp import run
        result = run("""
            (let ((make-adder (lambda (n) (lambda (x) (+ n x)))))
              (let ((add5 (make-adder 5)))
                (let ((add10 (make-adder 10)))
                  (let ((r1 (add5 3)))
                    (let ((r2 (add10 3)))
                      (+ r1 r2))))))
        """)
        assert result == 21  # 8 + 13


class TestInterpRecursion:
    """Letrec and recursive functions."""

    def test_factorial(self):
        from interp import run
        result = run("""
            (letrec ((fact (lambda (n)
              (let ((z (= n 0)))
                (if z
                  1
                  (let ((n1 (- n 1)))
                    (let ((r (fact n1)))
                      (* n r))))))))
              (fact 10))
        """)
        assert result == 3628800

    def test_mutual_recursion(self):
        from interp import run
        result = run("""
            (letrec ((is-even (lambda (n)
                       (let ((z (= n 0)))
                         (if z
                           #t
                           (let ((n1 (- n 1)))
                             (is-odd n1))))))
                     (is-odd (lambda (m)
                       (let ((z2 (= m 0)))
                         (if z2
                           #f
                           (let ((m1 (- m 1)))
                             (is-even m1)))))))
              (is-even 10))
        """)
        assert result is True


class TestInterpMutation:
    """Mutable state via set!."""

    def test_simple_set(self):
        from interp import run
        result = run("""
            (let ((x 0))
              (let ((_ (set! x 42)))
                x))
        """)
        assert result == 42

    def test_counter(self):
        from interp import run
        result = run("""
            (let ((count 0))
              (let ((inc (lambda ()
                          (let ((_ (set! count (+ count 1))))
                            count))))
                (let ((a (inc)))
                  (let ((b (inc)))
                    (let ((c (inc)))
                      (+ a (+ b c)))))))
        """)
        assert result == 6  # 1 + 2 + 3

    def test_mutation_rebind(self):
        """set! rebinds a variable from one lambda to another."""
        from interp import run
        result = run("""
            (let ((f (lambda (x) (+ x 1))))
              (let ((g (lambda (y) (* y 2))))
                (let ((_ (set! f g)))
                  (f 5))))
        """)
        assert result == 10


class TestInterpContinuations:
    """First-class continuations via call/cc."""

    def test_callcc_early_exit(self):
        from interp import run
        result = run("""
            (let ((f (lambda (k)
                       (let ((r (k 10)))
                         (+ 2 r)))))
              (let ((v (call/cc f)))
                (+ 1 v)))
        """)
        assert result == 11  # k(10) escapes; v=10, 1+10=11

    def test_callcc_no_escape(self):
        from interp import run
        result = run("""
            (let ((f (lambda (k) (+ 2 3))))
              (let ((v (call/cc f)))
                (+ 1 v)))
        """)
        assert result == 6  # f ignores k, returns 5; v=5, 1+5=6

    def test_callcc_multishot(self):
        """Multi-shot continuation creates a countdown loop via re-entry."""
        from interp import run
        result = run("""
            (let ((saved #f))
              (let ((n (call/cc (lambda (k)
                (let ((_ (set! saved k)))
                  5)))))
                (let ((small (< n 2)))
                  (if small
                    n
                    (let ((n1 (- n 1)))
                      (saved n1))))))
        """)
        # Countdown: 5->4->3->2->1, then 1<2 is true, returns 1
        assert result == 1

    def test_callcc_mutation_loop(self):
        """Multi-shot continuation with mutation creates a counted loop."""
        from interp import run
        result = run("""
            (let ((counter 0))
              (let ((saved #f))
                (let ((_ (call/cc (lambda (k)
                  (set! saved k)))))
                  (let ((_ (set! counter (+ counter 1))))
                    (let ((done (= counter 3)))
                      (if done
                        counter
                        (saved #f)))))))
        """)
        # Loop increments counter: 0->1->2->3, stops when counter==3
        assert result == 3


class TestFlowAnalysis:
    """Static analysis: flow-set correctness."""

    def test_simple_flow(self):
        """Direct bindings: each variable gets exactly its assigned lambda."""
        from analysis import analyze
        flow = analyze("""
            (let ((f (lambda (x) (+ x 1))))
              (let ((g (lambda (y) (* y 2))))
                (let ((r1 (f 5)))
                  (let ((r2 (g 10)))
                    (+ r1 r2)))))
        """)
        # f -> {1}, g -> {2}
        assert 1 in flow.get('f', set())
        assert 2 not in flow.get('f', set())
        assert 2 in flow.get('g', set())
        assert 1 not in flow.get('g', set())

    def test_higher_order_flow(self):
        """Higher-order apply merges flows through shared parameter."""
        from analysis import analyze
        flow = analyze("""
            (let ((apply-fn (lambda (func arg) (func arg))))
              (let ((inc (lambda (n) (+ n 1))))
                (let ((dbl (lambda (m) (* m 2))))
                  (let ((a (apply-fn inc 5)))
                    (let ((b (apply-fn dbl 10)))
                      (+ a b))))))
        """)
        # apply-fn is Lam#1
        assert 1 in flow.get('apply-fn', set())
        # func parameter gets both inc(#2) and dbl(#3)
        assert 2 in flow.get('func', set())
        assert 3 in flow.get('func', set())
        # apply-fn itself should NOT flow to func
        assert 1 not in flow.get('func', set())

    def test_lambda_returning_lambda(self):
        """Maker returns inner lambda; outer lambda should not leak."""
        from analysis import analyze
        flow = analyze("""
            (let ((maker (lambda (n) (lambda (x) (+ n x)))))
              (let ((add5 (maker 5)))
                (let ((add10 (maker 10)))
                  (let ((r1 (add5 3)))
                    (let ((r2 (add10 3)))
                      (+ r1 r2))))))
        """)
        # maker=#1, inner=#2
        assert 1 in flow.get('maker', set())
        assert 2 in flow.get('add5', set())
        assert 2 in flow.get('add10', set())
        # maker should NOT flow to add5/add10
        assert 1 not in flow.get('add5', set())
        assert 1 not in flow.get('add10', set())

    def test_identity_merging(self):
        """Identity function causes merging of all arguments."""
        from analysis import analyze
        flow = analyze("""
            (let ((id (lambda (v) v)))
              (let ((f (lambda (a) (+ a 1))))
                (let ((g (lambda (b) (* b 2))))
                  (let ((h (id f)))
                    (let ((j (id g)))
                      (let ((r (h 10)))
                        r))))))
        """)
        # id=#1, f=#2, g=#3
        assert flow.get('id', set()) == {1}
        assert flow.get('f', set()) == {2}
        assert flow.get('g', set()) == {3}
        # v (param of id) gets both f and g
        assert 2 in flow.get('v', set())
        assert 3 in flow.get('v', set())
        # h and j both get {2, 3} due to monovariant merging
        assert 2 in flow.get('h', set())
        assert 3 in flow.get('h', set())
        assert 2 in flow.get('j', set())
        assert 3 in flow.get('j', set())

    def test_mutation_flow(self):
        """set! adds new lambda labels to a variable's flow set."""
        from analysis import analyze
        flow = analyze("""
            (let ((f (lambda (x) (+ x 1))))
              (let ((g (lambda (y) (* y 2))))
                (let ((_ (set! f g)))
                  (f 5))))
        """)
        # f initially has L1 from let binding
        assert 1 in flow.get('f', set())
        # g has L2
        assert 2 in flow.get('g', set())
        # set! f g adds g's label (L2) to f's flow set
        assert 2 in flow.get('f', set())

    def test_mutation_higher_order_propagation(self):
        """Mutation-induced flow propagates through higher-order calls."""
        from analysis import analyze
        flow = analyze("""
            (let ((dispatch (lambda (h) (h 10))))
              (let ((a (lambda (x) (+ x 1))))
                (let ((b (lambda (y) (* y 2))))
                  (let ((_ (set! a b)))
                    (dispatch a)))))
        """)
        # dispatch=L1, a=L2, b=L3
        assert 1 in flow.get('dispatch', set())
        # a gets both L2 (from let) and L3 (from set! a b)
        assert 2 in flow.get('a', set())
        assert 3 in flow.get('a', set())
        assert 3 in flow.get('b', set())
        # h (param of dispatch) receives a's full flow set {L2, L3}
        assert 2 in flow.get('h', set())
        assert 3 in flow.get('h', set())

    def test_shared_closure_mutation_flow(self):
        """Flow through a closure that mutates a free variable."""
        from analysis import analyze
        flow = analyze("""
            (let ((box (lambda (v) v)))
              (let ((setter (lambda (new-fn)
                (set! box new-fn))))
                (let ((caller (lambda () (box 10))))
                  (let ((double (lambda (y) (* y 2))))
                    (let ((_ (setter double)))
                      (caller))))))
        """)
        # box=L1, setter=L2, caller=L3, double=L4
        # setter called with double: new-fn gets {L4}
        # set! box new-fn adds {L4} to box's flow
        assert 1 in flow.get('box', set())
        assert 4 in flow.get('box', set())
        assert 2 in flow.get('setter', set())
        assert 3 in flow.get('caller', set())
        assert 4 in flow.get('double', set())
        assert 4 in flow.get('new-fn', set())


class TestGraphVisualization:
    """DOT graph and SVG output for higher_order.scm analysis."""

    def test_dot_file_exists(self):
        assert os.path.isfile('/app/flow_graph.dot'), \
            "flow_graph.dot not found at /app/flow_graph.dot"

    def test_svg_file_exists(self):
        assert os.path.isfile('/app/flow_graph.svg'), \
            "flow_graph.svg not found at /app/flow_graph.svg"

    def test_svg_nonempty(self):
        size = os.path.getsize('/app/flow_graph.svg')
        assert size > 100, f"flow_graph.svg too small ({size} bytes), likely invalid"

    def test_svg_is_valid(self):
        with open('/app/flow_graph.svg') as f:
            content = f.read()
        assert '<svg' in content, "SVG file does not contain <svg> tag"

    def test_dot_is_digraph(self):
        with open('/app/flow_graph.dot') as f:
            content = f.read()
        assert 'digraph' in content, "DOT file missing 'digraph' keyword"

    def test_dot_has_lambda_nodes(self):
        with open('/app/flow_graph.dot') as f:
            content = f.read()
        assert 'L1' in content, "DOT graph missing lambda node L1"
        assert 'L2' in content, "DOT graph missing lambda node L2"
        assert 'L3' in content, "DOT graph missing lambda node L3"

    def test_dot_has_func_edges(self):
        """The higher_order.scm analysis should show L2 and L3 flowing to func."""
        with open('/app/flow_graph.dot') as f:
            content = f.read()
        # L2 (inc) must flow to func (parameter of apply-fn)
        assert re.search(r'"?L2"?\s*->\s*"?func"?', content), \
            "Missing edge from L2 to func in DOT graph"
        # L3 (dbl) must flow to func
        assert re.search(r'"?L3"?\s*->\s*"?func"?', content), \
            "Missing edge from L3 to func in DOT graph"

    def test_dot_has_variable_nodes(self):
        with open('/app/flow_graph.dot') as f:
            content = f.read()
        # apply-fn should appear as a variable node
        assert re.search(r'apply.fn', content), \
            "DOT graph missing variable node for apply-fn"

    def test_dot_lambda_box_shape(self):
        """Lambda nodes should have box shape."""
        with open('/app/flow_graph.dot') as f:
            content = f.read()
        assert 'box' in content, "DOT graph missing box shape for lambda nodes"
