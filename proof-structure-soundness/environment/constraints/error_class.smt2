; SMT-LIB2 constraint definition for case-split on signal: error_class
; Encoding: correctable=0, uncorrectable=1, fatal=2
(set-logic QF_LIA)
(declare-const error_class Int)

; Domain: valid signal encodings
(define-fun in_domain () Bool
  (and (>= error_class 0) (<= error_class 2)))

; Child case predicates
(define-fun case_P7a () Bool (= error_class 0))
(define-fun case_P7b () Bool (= error_class 1))
