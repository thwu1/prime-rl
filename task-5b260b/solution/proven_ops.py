#!/usr/bin/env python3

"""
Write the complete VerifiedListOps.lean file with all project issues fixed
and all 8 sorry placeholders replaced by valid Lean 4 proofs.

Fixes applied:
- Removed 'attribute [irreducible] myReverse' (was blocking simp on reverse theorems)
- Removed 'set_option maxHeartbeats 4000' (was throttling proof engine)
- Fixed filter_length statement from = to ≤ (equality is false; filtering can reduce length)

Proof strategies:
- Theorems 1,2,4: straightforward structural induction + simp
- Theorem 3: induction + simp + omega for Nat arithmetic
- Theorem 5: induction using theorems 1,2 as rewrite lemmas
- Theorem 6: induction using theorem 5 as rewrite lemma
- Theorem 7: induction using theorem 3 as rewrite lemma + omega
- Theorem 8: induction + case split on Bool predicate + omega
"""

PROVEN_LEAN = r'''/-!
# VerifiedListOps — Verified List Operations

Custom recursive list operations with formal correctness proofs.
The project should build without warnings via `lake build`.

Some theorems depend on others — you may need to complete proofs
in a specific order and reference earlier theorems as lemmas.

-/

namespace VerifiedListOps

/-! ## Definitions -/

/-- Append two lists. -/
def myAppend : List α → List α → List α
  | [], ys => ys
  | x :: xs, ys => x :: myAppend xs ys

/-- Reverse a list. -/
def myReverse : List α → List α
  | [] => []
  | x :: xs => myAppend (myReverse xs) [x]

/-- Compute the length of a list. -/
def myLength : List α → Nat
  | [] => 0
  | _ :: xs => 1 + myLength xs

/-- Map a function over a list. -/
def myMap (f : α → β) : List α → List β
  | [] => []
  | x :: xs => f x :: myMap f xs

/-- Filter elements satisfying a boolean predicate. -/
def myFilter (p : α → Bool) : List α → List α
  | [] => []
  | x :: xs => if p x then x :: myFilter p xs else myFilter p xs

/-! ## Unit Tests -/

example : myAppend [1, 2] [3, 4] = [1, 2, 3, 4] := by native_decide
example : myReverse [1, 2, 3] = [3, 2, 1] := by native_decide
example : myLength [1, 2, 3, 4] = 4 := by native_decide
example : myMap (· + 10) [1, 2, 3] = [11, 12, 13] := by native_decide
example : myFilter (· > 2) [1, 2, 3, 4, 5] = [3, 4, 5] := by native_decide

example : myReverse (myReverse [1, 2, 3]) = [1, 2, 3] := by native_decide
example : myAppend (myAppend [1] [2]) [3] = myAppend [1] (myAppend [2] [3]) := by native_decide
example : myLength (myAppend [1, 2] [3, 4, 5]) = 5 := by native_decide
example : myLength (myReverse [10, 20, 30]) = 3 := by native_decide

/-! ## Theorems

Replace every `sorry` below with a valid proof.
Theorems may depend on each other — pay attention to the dependency structure.
-/

/-- **Theorem 1**: Appending the empty list on the right is the identity. -/
theorem append_nil (xs : List α) : myAppend xs [] = xs := by
  induction xs with
  | nil => rfl
  | cons x xs ih => simp [myAppend, ih]

/-- **Theorem 2**: Append is associative. -/
theorem append_assoc (xs ys zs : List α) :
    myAppend (myAppend xs ys) zs = myAppend xs (myAppend ys zs) := by
  induction xs with
  | nil => rfl
  | cons x xs ih => simp [myAppend, ih]

/-- **Theorem 3**: Length distributes over append (additive). -/
theorem length_append (xs ys : List α) :
    myLength (myAppend xs ys) = myLength xs + myLength ys := by
  induction xs with
  | nil => simp [myAppend, myLength]
  | cons x xs ih =>
    simp only [myAppend, myLength]
    rw [ih]
    omega

/-- **Theorem 4**: Map distributes over append. -/
theorem map_append (f : α → β) (xs ys : List α) :
    myMap f (myAppend xs ys) = myAppend (myMap f xs) (myMap f ys) := by
  induction xs with
  | nil => rfl
  | cons x xs ih => simp [myAppend, myMap, ih]

/-- **Theorem 5**: Reverse distributes over append (reversing the order).
    May require `append_nil` and `append_assoc` as lemmas. -/
theorem reverse_append (xs ys : List α) :
    myReverse (myAppend xs ys) = myAppend (myReverse ys) (myReverse xs) := by
  induction xs with
  | nil => simp [myAppend, myReverse, append_nil]
  | cons x xs ih =>
    simp only [myAppend, myReverse]
    rw [ih, append_assoc]

/-- **Theorem 6**: Reverse is an involution (applying it twice yields the original).
    May require `reverse_append` as a lemma. -/
theorem reverse_reverse (xs : List α) :
    myReverse (myReverse xs) = xs := by
  induction xs with
  | nil => rfl
  | cons x xs ih =>
    simp only [myReverse]
    rw [reverse_append]
    simp [myReverse, myAppend, ih]

/-- **Theorem 7**: Reverse preserves length.
    May require `length_append` as a lemma. -/
theorem length_reverse (xs : List α) :
    myLength (myReverse xs) = myLength xs := by
  induction xs with
  | nil => rfl
  | cons x xs ih =>
    simp only [myReverse]
    rw [length_append, ih]
    simp [myLength]
    omega

/-- **Theorem 8**: Filtering never increases length. -/
theorem filter_length (p : α → Bool) (xs : List α) :
    myLength (myFilter p xs) ≤ myLength xs := by
  induction xs with
  | nil => simp [myFilter, myLength]
  | cons x xs ih =>
    simp only [myFilter]
    split <;> simp_all [myLength] <;> omega

end VerifiedListOps
'''

if __name__ == "__main__":
    with open("/app/VerifiedListOps.lean", "w") as f:
        f.write(PROVEN_LEAN)
    print("Wrote proven VerifiedListOps.lean with all fixes and proofs")
