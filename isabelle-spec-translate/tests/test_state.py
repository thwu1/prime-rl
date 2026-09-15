
import pytest
import sys
import os
import random

sys.path.insert(0, '/app')


# ============================================================
# Parser Tests — AVL.thy
# ============================================================

class TestParserAVL:
    @pytest.fixture(autouse=True)
    def setup(self):
        from parser import IsabelleParser
        self.parser = IsabelleParser()
        self.result = self.parser.parse('/app/theories/AVL.thy')

    def test_theory_name(self):
        assert self.result['theory_name'] == 'AVL'

    def test_imports(self):
        assert self.result['imports'] == ['Main']

    def test_datatypes(self):
        dt_names = [d['name'] for d in self.result['datatypes']]
        assert 'tree' in dt_names
        tree_dt = next(d for d in self.result['datatypes'] if d['name'] == 'tree')
        assert 'ET' in tree_dt['constructors']
        assert 'MKT' in tree_dt['constructors']

    def test_function_names_present(self):
        fn_names = [f['name'] for f in self.result['functions']]
        expected = ['height', 'avl', 'is_ord', 'is_in', 'ht', 'mkt',
                    'mkt_bal_l', 'mkt_bal_r', 'insert', 'delete_max',
                    'delete_root', 'delete', 'rightmost_item']
        for name in expected:
            assert name in fn_names, f"Function '{name}' not found in parsed functions"

    def test_function_kinds(self):
        fn_dict = {f['name']: f['kind'] for f in self.result['functions']}
        assert fn_dict.get('height') == 'primrec'
        assert fn_dict.get('avl') == 'primrec'
        assert fn_dict.get('is_in') == 'primrec'
        assert fn_dict.get('insert') == 'primrec'
        assert fn_dict.get('delete') == 'primrec'
        assert fn_dict.get('ht') == 'primrec'
        assert fn_dict.get('mkt') == 'definition'
        assert fn_dict.get('mkt_bal_l') == 'fun'
        assert fn_dict.get('mkt_bal_r') == 'fun'
        assert fn_dict.get('delete_max') == 'fun'
        assert fn_dict.get('delete_root') == 'fun'
        assert fn_dict.get('rightmost_item') == 'fun'

    def test_theorem_names(self):
        thm_names = [l['name'] for l in self.result['lemmas'] if l['kind'] == 'theorem']
        expected_theorems = ['avl_insert_aux', 'set_of_insert', 'avl_delete_aux',
                             'set_of_delete', 'is_in_correct', 'is_ord_insert',
                             'is_ord_delete']
        for name in expected_theorems:
            assert name in thm_names, f"Theorem '{name}' not found"

    def test_lemma_names_subset(self):
        lem_names = [l['name'] for l in self.result['lemmas'] if l['kind'] == 'lemma']
        expected_subset = ['height_mkt_bal_l', 'height_mkt_bal_r', 'avl_mkt',
                           'avl_mkt_bal_l', 'avl_mkt_bal_r', 'set_of_mkt_bal_l',
                           'set_of_mkt_bal_r', 'avl_delete_max', 'avl_delete_root']
        for name in expected_subset:
            assert name in lem_names, f"Lemma '{name}' not found"

    def test_minimum_lemma_count(self):
        all_names = [l['name'] for l in self.result['lemmas']]
        assert len(all_names) >= 20, \
            f"Expected at least 20 named lemmas/theorems, got {len(all_names)}"


# ============================================================
# Parser Tests — Dijkstra.thy
# ============================================================

class TestParserDijkstra:
    @pytest.fixture(autouse=True)
    def setup(self):
        from parser import IsabelleParser
        self.parser = IsabelleParser()
        self.result = self.parser.parse('/app/theories/Dijkstra.thy')

    def test_theory_name(self):
        assert self.result['theory_name'] == 'Dijkstra'

    def test_imports(self):
        imports = self.result['imports']
        assert 'Graph' in imports
        assert 'Weight' in imports
        assert len(imports) >= 3

    def test_locales(self):
        assert 'weighted_graph' in self.result['locales']
        assert 'Dijkstra' in self.result['locales']

    def test_function_names_present(self):
        fn_names = [f['name'] for f in self.result['functions']]
        for name in ['dijkstra', 'dinvar', 'pop_min', 'is_shortest_path_map']:
            assert name in fn_names, f"Function '{name}' not found in Dijkstra"

    def test_inductive_definition(self):
        fn_dict = {f['name']: f['kind'] for f in self.result['functions']}
        assert fn_dict.get('update_spec') == 'inductive'


# ============================================================
# AVL Implementation Tests — Basic Operations
# ============================================================

class TestAVLBasic:
    def setup_method(self):
        from avl import (ht, mkt, mkt_bal_l, mkt_bal_r, avl_insert,
                         delete_max, delete_root, avl_delete, is_in,
                         set_of, is_avl)
        self.ht = ht
        self.mkt = mkt
        self.mkt_bal_l = mkt_bal_l
        self.mkt_bal_r = mkt_bal_r
        self.avl_insert = avl_insert
        self.delete_max = delete_max
        self.delete_root = delete_root
        self.avl_delete = avl_delete
        self.is_in = is_in
        self.set_of = set_of
        self.is_avl = is_avl

    def _build_tree(self, values):
        t = None
        for v in values:
            t = self.avl_insert(v, t)
        return t

    def test_empty_tree(self):
        assert self.ht(None) == 0
        assert self.set_of(None) == set()
        assert self.is_avl(None)

    def test_single_insert(self):
        t = self.avl_insert(5, None)
        assert t == (5, None, None, 1)
        assert self.is_avl(t)

    def test_left_rotation(self):
        """Insert [1,2,3] triggers a single left rotation."""
        t = self._build_tree([1, 2, 3])
        assert t == (2, (1, None, None, 1), (3, None, None, 1), 2)

    def test_right_rotation(self):
        """Insert [3,2,1] triggers a single right rotation."""
        t = self._build_tree([3, 2, 1])
        assert t == (2, (1, None, None, 1), (3, None, None, 1), 2)

    def test_double_lr_rotation(self):
        """Insert [3,1,2] triggers a left-right double rotation."""
        t = self._build_tree([3, 1, 2])
        assert t == (2, (1, None, None, 1), (3, None, None, 1), 2)

    def test_double_rl_rotation(self):
        """Insert [1,3,2] triggers a right-left double rotation."""
        t = self._build_tree([1, 3, 2])
        assert t == (2, (1, None, None, 1), (3, None, None, 1), 2)

    def test_balanced_insert_no_rotation(self):
        """Insert [5,3,7,2,4,6,8] requires no rotations."""
        t = self._build_tree([5, 3, 7, 2, 4, 6, 8])
        expected = (5,
                    (3, (2, None, None, 1), (4, None, None, 1), 2),
                    (7, (6, None, None, 1), (8, None, None, 1), 2),
                    3)
        assert t == expected

    def test_duplicate_insert(self):
        """Inserting a duplicate must return the same tree."""
        t1 = self._build_tree([3, 1, 5])
        t2 = self.avl_insert(3, t1)
        assert t1 == t2


# ============================================================
# AVL Implementation Tests — Deletion
# ============================================================

class TestAVLDelete:
    def setup_method(self):
        from avl import (avl_insert, delete_max, delete_root,
                         avl_delete, set_of, is_avl)
        self.avl_insert = avl_insert
        self.delete_max = delete_max
        self.delete_root = delete_root
        self.avl_delete = avl_delete
        self.set_of = set_of
        self.is_avl = is_avl

    def _build_tree(self, values):
        t = None
        for v in values:
            t = self.avl_insert(v, t)
        return t

    def test_delete_from_empty(self):
        assert self.avl_delete(5, None) is None

    def test_delete_single_element(self):
        t = self.avl_insert(5, None)
        assert self.avl_delete(5, t) is None

    def test_delete_max_simple(self):
        """delete_max on tree {2,3,4} returns (4, remaining_tree)."""
        t = self._build_tree([3, 2, 4])
        val, remainder = self.delete_max(t)
        assert val == 4
        assert remainder == (3, (2, None, None, 1), None, 2)

    def test_delete_root_predecessor(self):
        """Deleting the root must use the predecessor (delete_max on left subtree).
        Delete 5 from the balanced tree built from [5,3,7,2,4,6,8]."""
        t = self._build_tree([5, 3, 7, 2, 4, 6, 8])
        result = self.avl_delete(5, t)
        # Predecessor of 5 is 4 (rightmost of left subtree)
        expected = (4,
                    (3, (2, None, None, 1), None, 2),
                    (7, (6, None, None, 1), (8, None, None, 1), 2),
                    3)
        assert result == expected

    def test_delete_with_rotation(self):
        """Deleting element 1 from tree built from [2,1,4,3,5] triggers rotation."""
        t = self._build_tree([2, 1, 4, 3, 5])
        result = self.avl_delete(1, t)
        expected = (4,
                    (2, None, (3, None, None, 1), 2),
                    (5, None, None, 1),
                    3)
        assert result == expected

    def test_delete_nonexistent(self):
        """Deleting a missing element must not change the tree."""
        t = self._build_tree([3, 1, 5])
        result = self.avl_delete(7, t)
        assert result == t


# ============================================================
# AVL Implementation Tests — Formal Properties
# ============================================================

class TestAVLProperties:
    def setup_method(self):
        from avl import avl_insert, avl_delete, set_of, is_avl, is_in
        self.avl_insert = avl_insert
        self.avl_delete = avl_delete
        self.set_of = set_of
        self.is_avl = is_avl
        self.is_in = is_in

    def _build_tree(self, values):
        t = None
        for v in values:
            t = self.avl_insert(v, t)
        return t

    def test_avl_invariant_after_inserts(self):
        """AVL invariant must hold after every insertion."""
        rng = random.Random(42)
        values = rng.sample(range(1000), 100)
        t = None
        for v in values:
            t = self.avl_insert(v, t)
            assert self.is_avl(t), f"AVL invariant violated after inserting {v}"

    def test_avl_invariant_after_deletes(self):
        """AVL invariant must hold after every deletion."""
        rng = random.Random(42)
        values = rng.sample(range(200), 50)
        t = self._build_tree(values)
        rng.shuffle(values)
        for v in values:
            t = self.avl_delete(v, t)
            assert self.is_avl(t), f"AVL invariant violated after deleting {v}"
        assert t is None

    def test_set_of_insert(self):
        """set_of(insert(x, t)) == {x} | set_of(t)"""
        t = self._build_tree([5, 3, 7])
        assert self.set_of(t) == {3, 5, 7}
        t = self.avl_insert(4, t)
        assert self.set_of(t) == {3, 4, 5, 7}

    def test_set_of_delete(self):
        """set_of(delete(x, t)) == set_of(t) - {x}"""
        t = self._build_tree([5, 3, 7, 2, 4, 6, 8])
        assert self.set_of(t) == {2, 3, 4, 5, 6, 7, 8}
        t = self.avl_delete(5, t)
        assert self.set_of(t) == {2, 3, 4, 6, 7, 8}
        t = self.avl_delete(2, t)
        assert self.set_of(t) == {3, 4, 6, 7, 8}

    def test_is_in_correct(self):
        """is_in must match set membership."""
        t = self._build_tree([10, 5, 15, 3, 7])
        for v in [10, 5, 15, 3, 7]:
            assert self.is_in(v, t), f"{v} should be in tree"
        for v in [1, 4, 6, 8, 11, 20]:
            assert not self.is_in(v, t), f"{v} should not be in tree"

    def test_insert_delete_stress(self):
        """Stress test: interleaved inserts and deletes preserve invariants."""
        rng = random.Random(123)
        values = list(range(50))
        rng.shuffle(values)
        t = None
        inserted = set()
        for v in values:
            t = self.avl_insert(v, t)
            inserted.add(v)
            assert self.set_of(t) == inserted
            assert self.is_avl(t)

        to_delete = values[:25]
        for v in to_delete:
            t = self.avl_delete(v, t)
            inserted.discard(v)
            assert self.set_of(t) == inserted
            assert self.is_avl(t)
