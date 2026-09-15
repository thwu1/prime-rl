(* seL4 l4v Proof Sessions
   Refinement, access control, information flow, and binary verification *)

session AInvs = ASpec +
  options [timeout = 14400]
  theories
    "AInvsToplevel_AI"

session BaseRefine = Lib +
  sessions
    ASpec
    ExecSpec
  theories
    "BaseRefine"

session Refine = BaseRefine +
  sessions
    ASpec
    ExecSpec
  theories
    "Refine"

session RefineOrphanage = Refine +
  theories
    "Orphanage"

(* CRefine sequence — C-level refinement proofs *)
session CBaseRefine = CSpec +
  sessions
    AutoCorres
    CLib
  theories
    "CBaseRefine"
    "Include_C"

session CRefine = CBaseRefine +
  options [timeout = 36000]
  theories
    "CRefine"

(* capDL refinement *)
session DBaseRefine = Lib +
  sessions
    AInvs
  theories
    "DBaseRefine"

session DRefine = DBaseRefine +
  theories
    "DRefine"

(* Access control and information flow *)
session Access = AInvs +
  theories
    "Access"

session InfoFlow = Access +
  theories
    "InfoFlow"

session InfoFlowCBase = InfoFlow +
  sessions
    CRefine
  theories
    "InfoFlowCBase"

session InfoFlowC = InfoFlowCBase +
  theories
    "InfoFlowC"

session DPolicy = DRefine +
  sessions
    Access
  theories
    "DPolicy"

session Bisim = AInvs +
  theories
    "Bisim"

session SimplExportAndRefine = CSpec +
  theories
    "SimplExportAndRefine"

(* Separation logic on capDL *)
session SepDSpec = DSpec +
  sessions
    SepTactics
  theories
    "SepDSpec"

session DSpecProofs = SepDSpec +
  theories
    "DSpecProofs"
