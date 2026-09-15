(* seL4 l4v Library Sessions
   Copyright 2020, Data61, CSIRO (ABN 41 687 119 230)
   SPDX-License-Identifier: BSD-2-Clause *)

session Lib = Word_Lib +
  sessions
    HOL-Eisbach
  theories
    "Lib"
    "Defs"
    "Eisbach_Methods"

session LibTest = Lib +
  theories
    "Corres_Test"
    "Crunch_Test_Toplevel"

session Sep_Algebra = HOL +
  theories
    "Sep_Algebra"
    "Map_Extra"

(* CLib provides C-specific verification infrastructure *)
session CLib = CParser +
  sessions
    Lib
    HOL-Statespace
  theories
    "CCorres_UL"
    "CCorresLemmas"
    "CLib"

session CorresK = Lib +
  sessions
    ASpec
    ExecSpec
  theories
    "CorresK"
    "Corres_Method"

session SepTactics = Sep_Algebra +
  sessions
    Lib
  theories
    "Hoare_Sep_Tactics"
