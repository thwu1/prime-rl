#!/bin/bash
set -e
cd /app

git config --global init.defaultBranch main
git config --global --add safe.directory /app
git init
git config user.email "dev@example.com"
git config user.name "Developer"

# Save current buffer.py (has optimization applied)
cp buffer.py /tmp/buffer_optimized.py

# Commit 1: Initial buffer implementation (correct persistence)
cp /tmp/buffer_v1.py buffer.py
git add buffer.py
GIT_AUTHOR_DATE="2024-09-15T10:00:00" GIT_COMMITTER_DATE="2024-09-15T10:00:00" \
    git commit -m "Add piece table buffer module

Implements a persistent piece table with structural sharing.
Each insert/delete returns a new PieceTable; all versions
share the underlying buffer storage via copied descriptor lists."

# Commit 2: Optimize insert (introduces shared-state mutation)
cp /tmp/buffer_optimized.py buffer.py
git add buffer.py
GIT_AUTHOR_DATE="2024-09-22T14:30:00" GIT_COMMITTER_DATE="2024-09-22T14:30:00" \
    git commit -m "Optimize buffer insert: skip redundant descriptor copy

Avoid allocating a new descriptor list on every insert by
operating on the existing list directly. Reduces allocation
overhead for sequential editing workloads."

# Commit 3: Add differ
git add differ.py
GIT_AUTHOR_DATE="2024-10-01T09:15:00" GIT_COMMITTER_DATE="2024-10-01T09:15:00" \
    git commit -m "Add line-based text diff module

Implements positional line comparison for generating edit
scripts between two text versions."

# Commit 4: Add history module
git add history.py
GIT_AUTHOR_DATE="2024-10-08T11:00:00" GIT_COMMITTER_DATE="2024-10-08T11:00:00" \
    git commit -m "Add undo/redo history module

Tracks document states with linear undo/redo navigation."

# Commit 5: Add session store stub and engine facade
git add session_store.py editor_engine.py
GIT_AUTHOR_DATE="2024-10-15T16:45:00" GIT_COMMITTER_DATE="2024-10-15T16:45:00" \
    git commit -m "Add session store stub and editor engine facade

SessionStore placeholder for SQLite-backed persistence.
EditorEngine re-exports all public API symbols."

# Cleanup temporary files
rm -f /tmp/buffer_optimized.py /tmp/buffer_v1.py
