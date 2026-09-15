(* seL4 l4v Specification Sessions
   Abstract, executable, and C-level specifications *)

session ASpec = Word_Lib +
  sessions
    Lib
  theories
    "Syscall_A"
    "Intro_Doc"
    "Glossary_Doc"

session ExecSpec = Word_Lib +
  sessions
    Lib
    HOL-Eisbach
  theories
    "API_H"
    "ArchIntermediate_H"

session DSpec = Word_Lib +
  sessions
    ExecSpec
    ASpec
  theories
    "Syscall_D"

session CSpec = CKernel +
  theories
    "KernelInc_C"
    "KernelState_C"

session CKernel = CParser +
  sessions
    ExecSpec
    CLib
    AsmRefine
  theories
    "Kernel_C"

session TakeGrant = Lib +
  theories
    "TakeGrant_Formal"

session ASepSpec = ASpec +
  theories
    "ASepSpec"
