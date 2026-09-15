#!r6rs

;; Copyright (C) Marc Nieper-Wißkirchen (2021).  All Rights Reserved.
;; MIT License

(library (control-features primitives)
  (export %call-with-current-continuation
	  %call-in-continuation
	  (rename [eq? %continuation=?])
	  %case-lambda-box %case-lambda-box-ref)
  (import (except (rnrs (6)) call-with-current-continuation)
	  (only (chezscheme) make-ephemeron-eq-hashtable))

  (define procedure-locations
    (let ([locations (make-ephemeron-eq-hashtable)])
      (lambda () locations)))

  (define-syntax %case-lambda-box
    (syntax-rules ()
      [(%case-lambda-box expr [formals body] ...)
       (let ([proc (case-lambda [formals body] ...)])
	 (hashtable-set! (procedure-locations) proc expr)
	 proc)]))

  (define %case-lambda-box-ref
    (lambda (proc default)
      (hashtable-ref (procedure-locations) proc default)))

  (define continuation
    (let ([continuations (make-ephemeron-eq-hashtable)])
      (case-lambda
       [(k) (hashtable-ref continuations k #f)]
       [(k c) (hashtable-update! continuations k values c)])))

  (define %call-with-current-continuation
    (lambda (proc)
      (call/cc
       (lambda (k)
	 ((call/cc
	   (lambda (abort-k)
	     (continuation k abort-k)
	     (lambda ()
	       (proc k)))))))))

  (define %call-in-continuation
    (lambda (k thunk)
      ((assert (continuation k)) thunk))))
