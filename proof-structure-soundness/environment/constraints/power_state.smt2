; SMT-LIB2 constraint definition for case-split on signal: power_state
; Encoding: active=0, idle=1, sleep=2, deep_sleep=3
(set-logic QF_LIA)
(declare-const power_state Int)

; Domain: valid signal encodings
(define-fun in_domain () Bool
  (and (>= power_state 0) (<= power_state 3)))

; Child case predicates (mixed constraint styles)
(define-fun case_P6a () Bool (= power_state 0))
(define-fun case_P6b () Bool (= power_state 1))
(define-fun case_P6c () Bool (and (>= power_state 2) (<= power_state 2)))
(define-fun case_P6d () Bool (not (and (>= power_state 0) (<= power_state 2))))
