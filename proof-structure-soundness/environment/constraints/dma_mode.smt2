; SMT-LIB2 constraint definition for case-split on signal: dma_mode
; Encoding: scatter=0, gather=1
(set-logic QF_LIA)
(declare-const dma_mode Int)

; Domain: valid signal encodings
(define-fun in_domain () Bool
  (and (>= dma_mode 0) (<= dma_mode 1)))

; Child case predicates (range-based constraints)
(define-fun case_P3a () Bool (and (>= dma_mode 0) (< dma_mode 1)))
(define-fun case_P3b () Bool (>= dma_mode 1))
