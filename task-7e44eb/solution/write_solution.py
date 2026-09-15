#!/usr/bin/env python3
"""Generate the complete Lean 4 solution for the NAE-SAT to 3-Coloring reduction.

The solution defines EdgeRelation, clauseNodeColor, and proves both
completeness and soundness of the reduction using only Lean 4 standard
library (no Mathlib).
"""


SOLUTION = r'''/-!
# NAE-SAT to 3-Coloring NP-Completeness Reduction (Complete Solution)

All definitions are self-contained (no Mathlib dependency).
-/

-- ═══════════════════════════════════════════════════════════════════
-- Helper utilities
-- ═══════════════════════════════════════════════════════════════════

private theorem fin3_cases (i : Fin 3) : i = 0 ∨ i = 1 ∨ i = 2 := by
  have := i.isLt
  have : i.val = 0 ∨ i.val = 1 ∨ i.val = 2 := by omega
  rcases this with h | h | h
  · left; exact Fin.ext h
  · right; left; exact Fin.ext h
  · right; right; exact Fin.ext h

private theorem list_all_mem {α : Type} {p : α → Bool}
    {l : List α} (hall : l.all p = true) {x : α} (hx : x ∈ l) : p x = true := by
  induction l with
  | nil => nomatch hx
  | cons a t ih =>
    have h1 : p a = true ∧ t.all p = true := by
      have : p a && t.all p = true := hall
      cases p a <;> cases t.all p <;> simp_all
    cases hx with
    | head => exact h1.1
    | tail _ hmem => exact ih h1.2 hmem

-- ═══════════════════════════════════════════════════════════════════
-- NAE-SAT definitions
-- ═══════════════════════════════════════════════════════════════════

structure NAEclause (V : Type) where
  v0 : V
  v1 : V
  v2 : V

def SatisfiesClause {V : Type} (assign : V → Bool) (c : NAEclause V) : Bool :=
  (assign c.v0 != assign c.v1 || assign c.v0 != assign c.v2 ||
   assign c.v1 != assign c.v2)

abbrev NAESat3 (V : Type) := List (NAEclause V)

def SatisfiesNAE3 {V : Type} (assign : V → Bool) (f : NAESat3 V) : Bool :=
  f.all (SatisfiesClause assign)

noncomputable def IsSatisfiable {V : Type} (f : NAESat3 V) : Prop :=
  ∃ (assign : V → Bool), SatisfiesNAE3 assign f = true

-- ═══════════════════════════════════════════════════════════════════
-- Reduction graph
-- ═══════════════════════════════════════════════════════════════════

inductive OutputVertex (V : Type)
| groundNode
| varNode (v : V)
| clauseNode (c : NAEclause V) (idx : Fin 3)

def EdgeRelation {V : Type} (clauses : NAESat3 V)
    (u v : OutputVertex V) : Prop :=
  match u, v with
  | .groundNode, .varNode _ => True
  | .varNode _, .groundNode => True
  | .varNode w, .clauseNode c i =>
    (w = c.v0 ∧ i = 0) ∨ (w = c.v1 ∧ i = 1) ∨ (w = c.v2 ∧ i = 2)
  | .clauseNode c i, .varNode w =>
    (w = c.v0 ∧ i = 0) ∨ (w = c.v1 ∧ i = 1) ∨ (w = c.v2 ∧ i = 2)
  | .clauseNode c1 i, .clauseNode c2 j => c1 = c2 ∧ c1 ∈ clauses ∧ i ≠ j
  | _, _ => False

def ReductionAdj {V : Type} (f : NAESat3 V)
    (u v : OutputVertex V) : Prop :=
  u ≠ v ∧ (EdgeRelation f u v ∨ EdgeRelation f v u)

def Is3Colorable {V : Type} (f : NAESat3 V) : Prop :=
  ∃ col : OutputVertex V → Fin 3,
    ∀ u v, ReductionAdj f u v → col u ≠ col v

-- ═══════════════════════════════════════════════════════════════════
-- Coloring functions
-- ═══════════════════════════════════════════════════════════════════

private def clauseNodeColor (a b c : Bool) (k : Fin 3) : Fin 3 :=
  match a, b, c, k.val with
  | true,  true,  false, 0 => 0
  | true,  true,  false, 1 => 2
  | true,  true,  false, _ => 1
  | true,  false, true,  0 => 0
  | true,  false, true,  1 => 1
  | true,  false, true,  _ => 2
  | false, true,  true,  0 => 1
  | false, true,  true,  1 => 0
  | false, true,  true,  _ => 2
  | true,  false, false, 0 => 2
  | true,  false, false, 1 => 0
  | true,  false, false, _ => 1
  | false, true,  false, 0 => 0
  | false, true,  false, 1 => 2
  | false, true,  false, _ => 1
  | false, false, true,  0 => 0
  | false, false, true,  1 => 1
  | false, false, true,  _ => 2
  | _,     _,     _,     _ => 0

private def naeColoring {V : Type} (assign : V → Bool) :
    OutputVertex V → Fin 3
  | .groundNode => 0
  | .varNode v => if assign v then 1 else 2
  | .clauseNode c k =>
      clauseNodeColor (assign c.v0) (assign c.v1) (assign c.v2) k

-- ═══════════════════════════════════════════════════════════════════
-- Completeness proof
-- ═══════════════════════════════════════════════════════════════════

lemma NAEtoColorCompleteness {V : Type} (f : NAESat3 V) :
    IsSatisfiable f → Is3Colorable f := by
  intro ⟨assign, hsat⟩
  refine ⟨naeColoring assign, ?_⟩
  intro u v ⟨_, hedge⟩
  suffices key : ∀ {a b : OutputVertex V}, EdgeRelation f a b →
              naeColoring assign a ≠ naeColoring assign b by
    rcases hedge with h | h
    · exact key h
    · exact fun heq => key h heq.symm
  intro a b h
  match a, b with
  | .groundNode, .groundNode => exact False.elim h
  | .groundNode, .varNode v =>
    simp only [naeColoring]
    cases assign v <;> decide
  | .varNode v, .groundNode =>
    simp only [naeColoring]
    cases assign v <;> decide
  | .groundNode, .clauseNode _ _ => exact False.elim h
  | .clauseNode _ _, .groundNode => exact False.elim h
  | .varNode _, .varNode _ => exact False.elim h
  | .varNode w, .clauseNode c k =>
    simp only [EdgeRelation] at h
    simp only [naeColoring]
    rcases h with ⟨rfl, rfl⟩ | ⟨rfl, rfl⟩ | ⟨rfl, rfl⟩ <;>
      (cases ha : assign c.v0 <;> cases hb : assign c.v1 <;>
       cases hc : assign c.v2 <;> simp_all [clauseNodeColor])
  | .clauseNode c k, .varNode w =>
    simp only [EdgeRelation] at h
    simp only [naeColoring]
    rcases h with ⟨rfl, rfl⟩ | ⟨rfl, rfl⟩ | ⟨rfl, rfl⟩ <;>
      (cases ha : assign c.v0 <;> cases hb : assign c.v1 <;>
       cases hc : assign c.v2 <;> simp_all [clauseNodeColor])
  | .clauseNode c1 i, .clauseNode c2 j =>
    obtain ⟨rfl, hcIn, hij⟩ := h
    simp only [naeColoring]
    have hNAE : SatisfiesClause assign c1 = true :=
      list_all_mem hsat hcIn
    rcases fin3_cases i with rfl | rfl | rfl <;>
      rcases fin3_cases j with rfl | rfl | rfl <;>
      (cases ha : assign c1.v0 <;> cases hb : assign c1.v1 <;>
       cases hc : assign c1.v2 <;>
       simp_all [clauseNodeColor, SatisfiesClause])

-- ═══════════════════════════════════════════════════════════════════
-- Soundness proof
-- ═══════════════════════════════════════════════════════════════════

lemma NAEtoColorSoundness {V : Type} (f : NAESat3 V) :
    Is3Colorable f → IsSatisfiable f := by
  intro ⟨col, hcol⟩
  have colNe : ∀ {u v : OutputVertex V},
      u ≠ v → (EdgeRelation f u v ∨ EdgeRelation f v u) → col u ≠ col v :=
    fun hne hedge => hcol _ _ ⟨hne, hedge⟩
  -- Variables differ from ground
  have hVG : ∀ v : V, col (.varNode v) ≠ col .groundNode := fun v =>
    colNe (fun h => nomatch h) (Or.inl trivial)
  -- Clause nodes in same clause have pairwise distinct colors (triangle)
  have hCC : ∀ (c : NAEclause V), c ∈ f → ∀ (i j : Fin 3), i ≠ j →
      col (.clauseNode c i) ≠ col (.clauseNode c j) := by
    intro c hcIn i j hij
    apply colNe
    · intro h; cases h; exact hij rfl
    · exact Or.inl ⟨rfl, hcIn, hij⟩
  -- Each clause node differs from its corresponding variable
  have hVC0 : ∀ c : NAEclause V, col (.clauseNode c 0) ≠ col (.varNode c.v0) := fun c =>
    Ne.symm (colNe (fun h => nomatch h) (Or.inl (Or.inl ⟨rfl, rfl⟩)))
  have hVC1 : ∀ c : NAEclause V, col (.clauseNode c 1) ≠ col (.varNode c.v1) := fun c =>
    Ne.symm (colNe (fun h => nomatch h) (Or.inl (Or.inr (Or.inl ⟨rfl, rfl⟩))))
  have hVC2 : ∀ c : NAEclause V, col (.clauseNode c 2) ≠ col (.varNode c.v2) := fun c =>
    Ne.symm (colNe (fun h => nomatch h) (Or.inl (Or.inr (Or.inr ⟨rfl, rfl⟩))))
  -- Define assignment from coloring
  let cTrue : Fin 3 := col .groundNode + 1
  let assign := fun v => decide (col (.varNode v) = cTrue)
  refine ⟨assign, ?_⟩
  simp only [SatisfiesNAE3]
  -- Show every clause is NAE-satisfied
  suffices ∀ c ∈ f, SatisfiesClause assign c = true by
    induction f with
    | nil => simp [List.all]
    | cons a t ih =>
      simp only [List.all, Bool.and_eq_true]
      exact ⟨this a (List.mem_cons_self a t),
             ih (fun c hc => this c (List.mem_cons_of_mem a hc))⟩
  intro c hcIn
  by_contra hFalse
  have hSatF : SatisfiesClause assign c = false := by
    cases hsc : SatisfiesClause assign c
    · rfl
    · exfalso; exact hFalse hsc
  simp only [SatisfiesClause] at hSatF
  have hall : assign c.v0 = assign c.v1 ∧ assign c.v0 = assign c.v2 := by
    constructor <;>
      (cases h0 : assign c.v0 <;> cases h1 : assign c.v1 <;>
       cases h2 : assign c.v2 <;> simp_all)
  obtain ⟨h01, h02⟩ := hall
  have hSameColor : col (.varNode c.v0) = col (.varNode c.v1) ∧
                    col (.varNode c.v0) = col (.varNode c.v2) := by
    cases hb : assign c.v0 with
    | true =>
      have ht0 : col (.varNode c.v0) = cTrue := of_decide_eq_true hb
      have ht1 : col (.varNode c.v1) = cTrue := of_decide_eq_true (h01.symm.trans hb)
      have ht2 : col (.varNode c.v2) = cTrue := of_decide_eq_true (h02.symm.trans hb)
      exact ⟨ht0.trans ht1.symm, ht0.trans ht2.symm⟩
    | false =>
      have hf0 : col (.varNode c.v0) ≠ cTrue := of_decide_eq_false hb
      have hf1 : col (.varNode c.v1) ≠ cTrue := of_decide_eq_false (h01.symm.trans hb)
      have hf2 : col (.varNode c.v2) ≠ cTrue := of_decide_eq_false (h02.symm.trans hb)
      have hg0 := hVG c.v0; have hg1 := hVG c.v1; have hg2 := hVG c.v2
      have hcTneG : (col .groundNode + 1 : Fin 3) ≠ col .groundNode := by
        rcases fin3_cases (col .groundNode) with h | h | h <;> (rw [h]; decide)
      constructor
      · apply Fin.ext
        have := (col .groundNode).isLt
        have := (col (.varNode c.v0)).isLt
        have := (col (.varNode c.v1)).isLt
        have := fun h => hg0 (Fin.ext h); have := fun h => hg1 (Fin.ext h)
        have := fun h => hf0 (Fin.ext h); have := fun h => hf1 (Fin.ext h)
        have := fun h => hcTneG (Fin.ext h)
        omega
      · apply Fin.ext
        have := (col .groundNode).isLt
        have := (col (.varNode c.v0)).isLt
        have := (col (.varNode c.v2)).isLt
        have := fun h => hg0 (Fin.ext h); have := fun h => hg2 (Fin.ext h)
        have := fun h => hf0 (Fin.ext h); have := fun h => hf2 (Fin.ext h)
        have := fun h => hcTneG (Fin.ext h)
        omega
  -- Pigeonhole contradiction
  obtain ⟨hcol01, hcol02⟩ := hSameColor
  have hVC0c := hVC0 c
  have hVC1c : col (.clauseNode c 1) ≠ col (.varNode c.v0) :=
    fun h => hVC1 c (h.trans hcol01)
  have hVC2c : col (.clauseNode c 2) ≠ col (.varNode c.v0) :=
    fun h => hVC2 c (h.trans hcol02)
  have cn0 := (col (.clauseNode c 0)).isLt
  have cn1 := (col (.clauseNode c 1)).isLt
  have cn2 := (col (.clauseNode c 2)).isLt
  have cvx := (col (.varNode c.v0)).isLt
  have ne01 : (col (.clauseNode c 0)).val ≠ (col (.clauseNode c 1)).val :=
    fun h => hCC c hcIn 0 1 (by decide) (Fin.ext h)
  have ne02 : (col (.clauseNode c 0)).val ≠ (col (.clauseNode c 2)).val :=
    fun h => hCC c hcIn 0 2 (by decide) (Fin.ext h)
  have ne12 : (col (.clauseNode c 1)).val ≠ (col (.clauseNode c 2)).val :=
    fun h => hCC c hcIn 1 2 (by decide) (Fin.ext h)
  have nex0 : (col (.clauseNode c 0)).val ≠ (col (.varNode c.v0)).val :=
    fun h => hVC0c (Fin.ext h)
  have nex1 : (col (.clauseNode c 1)).val ≠ (col (.varNode c.v0)).val :=
    fun h => hVC1c (Fin.ext h)
  have nex2 : (col (.clauseNode c 2)).val ≠ (col (.varNode c.v0)).val :=
    fun h => hVC2c (Fin.ext h)
  omega

-- ═══════════════════════════════════════════════════════════════════
-- Main theorem
-- ═══════════════════════════════════════════════════════════════════

theorem NAEtoColorReduction {V : Type} (f : NAESat3 V) :
    IsSatisfiable f ↔ Is3Colorable f :=
  Iff.intro (NAEtoColorCompleteness f) (NAEtoColorSoundness f)
'''

with open("/app/Reduction.lean", "w") as f:
    f.write(SOLUTION.lstrip())

print("Solution written to /app/Reduction.lean")
