#!/usr/bin/env bash

cp /solution/buffer_fixed.py /app/buffer.py
cp /solution/history_fixed.py /app/history.py
cp /solution/differ_fixed.py /app/differ.py
cp /solution/session_store_fixed.py /app/session_store.py

cd /app
python3 -c "
from editor_engine import PieceTable, UndoTree, myers_diff, SessionStore

# Verify buffer persistence
pt1 = PieceTable('Hello')
pt2 = pt1.insert(5, ' World')
pt3 = pt1.insert(0, 'Z')
assert pt1.get_text() == 'Hello', 'persistence broken'
assert pt2.get_text() == 'Hello World', 'insert broken'
assert pt3.get_text() == 'ZHello', 'divergent insert broken'

# Verify undo tree branching
tree = UndoTree('AB')
tree.apply_insert(2, 'C')
tree.undo()
tree.apply_insert(2, 'D')
tree.undo()
assert tree.get_children_count() == 2, 'branching broken'
s = tree.get_tree_structure()
assert s['id'] == 0 and len(s['children']) == 2, 'tree structure broken'

# Verify diff optimality
result = myers_diff('A\nC\n', 'A\nB\nC\n')
edits = sum(1 for l in result if l[0] in '+-')
assert edits == 1, f'diff not minimal: {edits} edits'

# Verify merge
tree2 = UndoTree('aaa\nbbb\nccc\n')
tree2.apply_delete(4, 4)
tree2.apply_insert(4, 'XXX\n')
na = tree2.current_node_id
tree2.undo()
tree2.undo()
tree2.apply_delete(8, 4)
tree2.apply_insert(8, 'YYY\n')
nb = tree2.current_node_id
mid = tree2.merge_branches(na, nb)
assert tree2.get_node_text(mid) == 'aaa\nXXX\nYYY\n', 'merge broken'

# Verify session store
store = SessionStore('/app/sessions.db')
sessions = store.list_sessions()
assert len(sessions) >= 2, 'list_sessions broken'
tree3 = store.replay_session('session_alpha')
assert 'Beautiful' in tree3.current_text(), 'replay broken'

print('All verifications passed')
"
