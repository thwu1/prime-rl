#!r6rs

;; Copyright (C) Marc Nieper-Wißkirchen (2021).  All Rights Reserved.
;; MIT License

(library (control-features timer)
  (export %call-with-interrupt-handler %set-timer!)
  (import (rnrs (6))
	  (only (chezscheme) parameterize timer-interrupt-handler set-timer))

  (define %call-with-interrupt-handler
    (lambda (handler thunk)
      (parameterize ([timer-interrupt-handler handler])
	(dynamic-wind
	    (lambda () (%set-timer! #t))
	    thunk
	    (lambda () (%set-timer! #f))))))

  (define %set-timer!
    (lambda (on?)
      (set-timer (if on? 1000 0)))))
