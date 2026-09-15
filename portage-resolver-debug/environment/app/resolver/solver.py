"""
Dependency resolver with backtracking for Gentoo-style packages.

Algorithm overview:
  1. For each requested atom, find matching package versions.
  2. Try the newest matching version first.
  3. Recursively resolve that version's dependencies.
  4. On conflict, backtrack and try the next-newest version.
  5. Track occupied slots to detect conflicts.

Slot-operator (``:=``) rebuild propagation:
  When a package's subslot changes between two solutions, every package
  that depends on it via ``:=`` must be rebuilt — transitively, because
  the rebuilt package may itself change its subslot.
"""

from .atom import Atom
from .depstring import evaluate
from .database import PackageDB
from .version import Version


# ── Exceptions ────────────────────────────────────────────────────────

class ResolverError(Exception):
    """Base class for resolver errors."""


class SlotConflict(ResolverError):
    """Two packages claim the same slot with different versions."""


class CircularDependency(ResolverError):
    """A dependency cycle was detected."""


class Unresolvable(ResolverError):
    """No valid resolution exists for a dependency."""


# ── Solution container ────────────────────────────────────────────────

class Solution:
    """A mutable package-installation plan."""

    def __init__(self):
        self.packages = []           # [(cp, version, slot, subslot), ...]
        self._slot_map = {}          # {cp: {slot: (version, subslot)}}

    # -- mutators ------------------------------------------------------

    def add(self, cp: str, version: str, slot: str, subslot: str):
        """Add a package.  Raises :class:`SlotConflict` on collision."""
        if cp in self._slot_map and slot in self._slot_map[cp]:
            cur_ver, _ = self._slot_map[cp][slot]
            if cur_ver == version:
                return                  # already present — nothing to do
            raise SlotConflict(
                f"{cp}:{slot} conflict: installed {cur_ver}, need {version}")

        self.packages.append((cp, version, slot, subslot))
        self._slot_map.setdefault(cp, {})[slot] = (version, subslot)

    def remove(self, cp: str, version: str):
        """Remove a package entry (used during backtracking)."""
        self.packages = [
            row for row in self.packages
            if not (row[0] == cp and row[1] == version)
        ]
        # NOTE: _slot_map is intentionally not updated here to preserve
        # slot allocation history for conflict diagnostics.

    # -- queries -------------------------------------------------------

    def has(self, cp: str) -> bool:
        """Return whether *cp* appears in the current plan."""
        return any(row[0] == cp for row in self.packages)

    def get_version(self, cp: str) -> str | None:
        """Return the planned version string for *cp*, or ``None``."""
        for c, v, *_ in self.packages:
            if c == cp:
                return v
        return None

    def get_subslot(self, cp: str, slot: str) -> str | None:
        """Return the recorded subslot for *cp*:*slot*, or ``None``."""
        if cp in self._slot_map and slot in self._slot_map[cp]:
            return self._slot_map[cp][slot][1]
        return None

    def copy(self):
        """Return a shallow copy of this solution."""
        s = Solution()
        s.packages = list(self.packages)
        s._slot_map = {cp: dict(m) for cp, m in self._slot_map.items()}
        return s

    def __repr__(self):
        return f"Solution({self.packages})"


# ── Resolver ──────────────────────────────────────────────────────────

class Resolver:
    """Dependency resolver with backtracking."""

    def __init__(self, db: PackageDB, use_flags: set[str]):
        self.db = db
        self.use_flags = use_flags

    # -- public API ----------------------------------------------------

    def resolve(self, requests: list[str]) -> Solution:
        """Resolve a list of atom strings into an installation plan."""
        solution = Solution()
        for req in requests:
            atom = Atom(req)
            self._resolve_one(atom, solution, resolving=set())
        return solution

    # -- internal ------------------------------------------------------

    def _resolve_one(self, atom: Atom, solution: Solution,
                     resolving: set):
        """Resolve a single atom, installing it and its deps."""
        cp = atom.cp

        # Already in the solution?
        if solution.has(cp):
            cur = solution.get_version(cp)
            if atom.matches_package(cp, cur):
                return
            raise SlotConflict(
                f"{cp}: installed {cur} does not satisfy {atom.raw}")

        # Cycle detection
        if cp in resolving:
            raise CircularDependency(
                f"Cycle: {' -> '.join(sorted(resolving))} -> {cp}")

        # Gather candidate versions, prefer newest
        versions = self.db.get_versions(cp)
        if not versions:
            raise Unresolvable(f"Package not found: {cp}")

        candidates = [
            (v, d) for v, d in versions.items()
            if atom.matches_package(cp, v, d.get('slot'), d.get('subslot'))
        ]
        if not candidates:
            raise Unresolvable(f"No version matches {atom.raw}")

        candidates.sort(key=lambda pair: Version(pair[0]), reverse=True)

        # Try each candidate, backtracking on failure
        last_err = None
        for ver, data in candidates:
            slot = data.get('slot', '0')
            subslot = data.get('subslot', slot)

            try:
                solution.add(cp, ver, slot, subslot)
            except SlotConflict as exc:
                last_err = exc
                continue

            try:
                dep_str = data.get('deps', '')
                dep_atoms = (evaluate(dep_str, self.use_flags)
                             if dep_str else [])
                child_stack = resolving | {cp}
                for da in dep_atoms:
                    self._resolve_one(da, solution, child_stack)
                return  # success — all deps satisfied
            except ResolverError as exc:
                last_err = exc
                solution.remove(cp, ver)
                continue

        raise Unresolvable(f"Cannot satisfy {atom.raw}: {last_err}")

    # -- rebuild propagation -------------------------------------------

    def compute_rebuilds(self, old: Solution, new: Solution) -> set[str]:
        """Determine packages needing rebuild after subslot changes.

        When a dependency's subslot changes, every package that depends
        on it with ``:=`` must be rebuilt — transitively.
        """
        rebuilds: set[str] = set()

        for cp, ver, slot, sub in new.packages:
            old_sub = old.get_subslot(cp, slot)
            if old_sub is not None and old_sub != sub:
                self._collect_slot_op_rdeps(cp, slot, new, rebuilds)

        return rebuilds

    def _collect_slot_op_rdeps(self, changed_cp: str, changed_slot: str,
                                solution: Solution,
                                rebuilds: set[str]):
        """Collect reverse-deps that use ``:=`` on *changed_cp*."""
        for cp, ver, slot, sub in solution.packages:
            if cp == changed_cp or cp in rebuilds:
                continue
            data = self.db.get_version(cp, ver)
            if not data:
                continue
            dep_str = data.get('deps', '')
            if not dep_str:
                continue
            for da in evaluate(dep_str, self.use_flags):
                if da.cp == changed_cp and da.slot_operator == '=':
                    rebuilds.add(cp)
                    break
