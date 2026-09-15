#!r6rs

;; Copyright (C) Marc Nieper-Wißkirchen (2021).  All Rights Reserved.
;; MIT License

(library (control-features testing)
  (export test-begin test-end test)
  (import (rnrs (6))
	  (control-features define-who)
	  (only (control-features) run))

  (define *count* 0)
  (define *fail* #f)

  (define test-begin
    (lambda (name)
      (display "# Starting test ")
      (display name)
      (newline)))

  (define test-end
    (lambda ()
      (display "1..")
      (display *count*)
      (newline)
      (when *fail*
	(exit #f))))

  (define-syntax/who test
    (lambda (stx)
      (syntax-case stx ()
	[(_ expected-expr test-expr)
	 #'(test #f expected-expr test-expr)]
	[(_ name expected-expr test-expr)
	 #'(let-values ([expected expected-expr]
			[result (run (lambda () test-expr))])
	     (do-test name expected result))]
	[_
	 (syntax-violation who "invalid syntax" stx)])))

  (define do-test
    (lambda (name expected result)
      (set! *count* (fx+ *count* 1))
      (if (equal? expected result)
	  (display "ok ")
	  (begin
	    (set! *fail* #t)
	    (display "not ok ")))
      (display *count*)
      (when name
	(display " - ")
	(display name))
      (newline))))
