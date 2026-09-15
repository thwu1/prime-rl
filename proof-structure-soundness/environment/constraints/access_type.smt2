; SMT-LIB2 constraint definition for case-split on signal: access_type
; Encoding: READ=0, WRITE=1, RMW=2, BURST=3
(set-logic QF_LIA)
(declare-const access_type Int)

; Domain: valid signal encodings
(define-fun in_domain () Bool
  (and (>= access_type 0) (<= access_type 3)))

; Child case predicates
(define-fun case_P1a () Bool (= access_type 0))
(define-fun case_P1b () Bool (= access_type 1))
