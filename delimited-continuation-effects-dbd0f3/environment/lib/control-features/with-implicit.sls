#!r6rs

;; Copyright (C) Marc Nieper-Wißkirchen (2021).  All Rights Reserved.
;; MIT License

(library (control-features with-implicit)
  (export with-implicit)
  (import (rnrs (6)))

  (define-syntax with-implicit
    (lambda (stx)
      (syntax-case stx ()
        ((_ (k x* ...) e e* ...)
         #'(with-syntax ((x* (datum->syntax #'k 'x*)) ...)
             e e* ...))
        (_
         (syntax-violation 'with-implicit "illegal syntax" stx))))))
