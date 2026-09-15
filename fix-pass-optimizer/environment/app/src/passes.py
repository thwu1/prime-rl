
"""Available LLVM passes and empirical synergy pair data.

Synergy pairs are derived from empirical measurements of pass interaction
effects on instruction count reduction across compiler benchmark suites.
Each pair (A, B) with score S indicates that running pass A immediately
before pass B tends to produce effective optimization, with higher scores
indicating stronger synergy.
"""

AVAILABLE_PASSES = [
    "sroa",
    "instcombine",
    "simplifycfg",
    "gvn",
    "early-cse",
    "dse",
    "adce",
    "licm",
    "loop-unroll",
    "mem2reg",
    "reassociate",
    "loop-rotate",
    "loop-simplify",
    "indvars",
    "jump-threading",
    "sccp",
    "aggressive-instcombine",
    "loop-idiom",
    "loop-deletion",
    "tailcallelim",
]

SYNERGY_PAIRS = {
    ("mem2reg", "sroa"): 95,
    ("mem2reg", "instcombine"): 90,
    ("mem2reg", "simplifycfg"): 85,
    ("sroa", "instcombine"): 92,
    ("sroa", "early-cse"): 88,
    ("instcombine", "simplifycfg"): 90,
    ("instcombine", "gvn"): 85,
    ("instcombine", "dse"): 82,
    ("simplifycfg", "instcombine"): 87,
    ("simplifycfg", "jump-threading"): 80,
    ("gvn", "instcombine"): 88,
    ("gvn", "simplifycfg"): 83,
    ("gvn", "dse"): 79,
    ("early-cse", "instcombine"): 91,
    ("early-cse", "simplifycfg"): 84,
    ("dse", "instcombine"): 78,
    ("dse", "adce"): 76,
    ("adce", "simplifycfg"): 75,
    ("licm", "loop-rotate"): 86,
    ("licm", "loop-simplify"): 82,
    ("licm", "indvars"): 80,
    ("loop-rotate", "licm"): 84,
    ("loop-rotate", "indvars"): 81,
    ("loop-rotate", "loop-unroll"): 83,
    ("loop-simplify", "loop-rotate"): 85,
    ("loop-simplify", "licm"): 80,
    ("indvars", "loop-unroll"): 82,
    ("indvars", "loop-deletion"): 77,
    ("loop-unroll", "instcombine"): 89,
    ("loop-unroll", "simplifycfg"): 85,
    ("reassociate", "instcombine"): 86,
    ("reassociate", "gvn"): 80,
    ("sccp", "instcombine"): 84,
    ("sccp", "simplifycfg"): 82,
    ("jump-threading", "simplifycfg"): 81,
    ("jump-threading", "instcombine"): 77,
    ("aggressive-instcombine", "instcombine"): 88,
    ("loop-idiom", "loop-deletion"): 74,
    ("loop-deletion", "simplifycfg"): 73,
    ("loop-deletion", "adce"): 72,
    ("tailcallelim", "instcombine"): 75,
}
