"""
API specification for the automated program repair pipeline.

The pipeline must be implemented in /app/pipeline/ and expose the following:

1. pipeline.coverage.CoverageCollector
   - Context manager collecting line-level coverage via sys.settrace
   - Constructor: CoverageCollector(target_func_name: Optional[str] = None)
   - Method: coverage() -> Set[Tuple[str, int]]
     Returns set of (function_name, line_number) for all covered lines.

   Usage:
       ns = {}
       exec(compile(source_code, '<src>', 'exec'), ns)
       with CoverageCollector('my_func') as cc:
           ns['my_func'](args)
       cov = cc.coverage()  # e.g. {('my_func', 2), ('my_func', 3)}

2. pipeline.fault_loc.ochiai
   - Function: ochiai(passed_coverage, failed_coverage)
       -> Dict[Tuple[str, int], float]
   - passed_coverage: List of coverage sets from passing test runs
   - failed_coverage: List of coverage sets from failing test runs
   - Returns suspiciousness score in [0.0, 1.0] for each covered location
   - Formula: ochiai(e) = ef / sqrt(total_failed * (ef + ep))
     where ef = number of failing runs covering e,
           ep = number of passing runs covering e,
           total_failed = total number of failing runs

3. pipeline.repair_program  (imported from pipeline.__init__)
   - Function: repair_program(source_code: str,
                               test_cases: List[Tuple[tuple, Any]],
                               function_name: str) -> str
   - source_code: Python source defining the buggy function
   - test_cases: list of (args_tuple, expected_result) pairs
   - function_name: name of the function to repair
   - Returns: repaired Python source code as a string
   - Must internally use coverage collection, Ochiai fault localization,
     suspiciousness-weighted AST mutation via genetic programming
     (population >= 20), and delta debugging minimization.

Example test cases for provided programs:

  MIDDLE_TESTS = [
      ((1, 2, 3), 2), ((3, 2, 1), 2), ((2, 1, 3), 2),
      ((1, 3, 2), 2), ((3, 1, 2), 2), ((2, 3, 1), 2),
      ((1, 1, 2), 1), ((2, 1, 1), 1), ((1, 2, 2), 2),
      ((5, 5, 5), 5),
  ]

  GCD_TESTS = [
      ((12, 8), 4), ((8, 12), 4), ((7, 5), 1),
      ((100, 75), 25), ((0, 5), 5), ((5, 0), 5),
      ((17, 17), 17), ((1, 1), 1), ((36, 24), 12),
      ((48, 18), 6),
  ]

  POWER_TESTS = [
      ((2, 0), 1), ((2, 1), 2), ((2, 3), 8), ((2, 10), 1024),
      ((3, 2), 9), ((3, 3), 27), ((5, 1), 5), ((10, 2), 100),
      ((1, 100), 1), ((7, 3), 343),
  ]
"""
