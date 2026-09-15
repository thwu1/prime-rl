#!r6rs

;; Copyright (C) Marc Nieper-Wißkirchen (2021).  All Rights Reserved.
;; MIT License

(library (control-features define-who)
  (export define/who
	  define-syntax/who)
  (import (rnrs (6))
	  (control-features with-implicit))

  (define-syntax define/who
    (lambda (x)
      (define out
        (lambda (k f e)
          (with-syntax ((k k) (f f) (e e))
            (with-implicit (k who)
              #'(define f
                  (let ((who 'f)) e))))))
      (syntax-case x ()
        ((k (f . u*) e e* ...)
	 (identifier? #'f)
	 (out #'k #'f #'(lambda u* e e* ...)))
        ((k f e)
	 (identifier? #'f)
         (out #'k #'f #'e))
        (_
         (syntax-violation 'define/who "invalid syntax" x)))))

  (define-syntax define-syntax/who
    (lambda (x)
      (syntax-case x ()
	[(k name expr)
	 (identifier? #'name)
	 (with-implicit (k who)
	   #'(define-syntax name
	       (let ([who 'name])
		 expr)))]
	[_
	 (syntax-violation 'define-syntax/who "invalid syntax" x)]))))
