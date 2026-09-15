(* seL4 l4v Tool Sessions
   C parser, AutoCorres abstraction, assembly refinement *)

session CParser = Word_Lib +
  theories
    "CTranslation"
    "PackedTypes"

session AutoCorres = CParser +
  theories
    "AutoCorres"
    "NonDetMonadEx"

session AsmRefine = CParser +
  theories
    "AsmRefine"
