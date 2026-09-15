#!/bin/bash

cat > /app/effects.scm << 'SCHEMEEOF'
#!r6rs

(import (except (rnrs (6))
                call-with-current-continuation call/cc
                dynamic-wind with-exception-handler guard
                raise raise-continuable
                current-input-port current-output-port current-error-port
                with-input-from-file with-output-to-file
                read-char peek-char read write-char newline display write)
        (prefix (rnrs (6)) rnrs:)
        (control-features))

;;; Part 1: shift/reset

(define-syntax reset
  (syntax-rules ()
    [(reset e1 e2 ...)
     (call-with-continuation-prompt
       (lambda () e1 e2 ...))]))

(define-syntax shift
  (syntax-rules ()
    [(shift k e1 e2 ...)
     (call-with-composable-continuation
       (lambda (c)
         (let ([k (lambda args (reset (apply c args)))])
           (abort-current-continuation (default-continuation-prompt-tag)
             (lambda () e1 e2 ...)))))]))

;;; Part 2: shift-at/reset-at

(define-syntax reset-at
  (syntax-rules ()
    [(reset-at tag e1 e2 ...)
     (call-with-continuation-prompt
       (lambda () e1 e2 ...)
       tag)]))

(define-syntax shift-at
  (syntax-rules ()
    [(shift-at tag-expr k e1 e2 ...)
     (let ([tag tag-expr])
       (call-with-composable-continuation
         (lambda (c)
           (let ([k (lambda args
                      (reset-at tag (apply c args)))])
             (abort-current-continuation tag
               (lambda () e1 e2 ...))))
         tag))]))

;;; Part 3: run-with-state (CPS handler loop via shift-at/reset-at)

(define run-with-state
  (lambda (proc seed)
    (define tag (make-continuation-prompt-tag))
    (let f ((val seed)
            (k (lambda ()
                 (reset-at
                  tag
                  (call-with-values
                    (lambda ()
                      (proc (lambda ()
                              (shift-at tag k
                                (lambda (g p f) (g k))))
                            (lambda (v)
                              (shift-at tag k
                                (lambda (g p f) (p k v))))))
                    (lambda args
                      (lambda (g p f)
                        (apply f args))))))))
      ((k)
       (lambda (k) (f val (lambda () (k val))))
       (lambda (k new-val) (f new-val k))
       values))))

;;; Part 4: amb/fail/collect-all

(define fail
  (lambda ()
    (shift k '())))

(define collect-all
  (lambda (thunk)
    (reset
      (let ([result (thunk)])
        (list result)))))

(define amb
  (lambda (choices)
    (shift k
      (let loop ([cs choices])
        (if (null? cs)
            '()
            (let ([head (k (car cs))])
              (append head (loop (cdr cs)))))))))

;;; Part 5: Streams

(define stream-null (make-promise '()))

(define stream-null?
  (lambda (stream) (null? (force stream))))

(define stream-car
  (lambda (stream) (force (car (force stream)))))

(define stream-cdr
  (lambda (stream) (cdr (force stream))))

(define-syntax stream-cons
  (syntax-rules ()
    [(stream-cons car-expr cdr-expr)
     (make-promise
       (cons (delay car-expr)
             (delay (force cdr-expr))))]))

(define-syntax stream-lambda
  (syntax-rules ()
    [(stream-lambda formals body1 ... body2)
     (lambda formals
       (delay (force (letrec* () body1 ... body2))))]))

(define for-each->stream
  (stream-lambda (for-each-proc seq)
    (reset
      (for-each-proc
        (lambda (el)
          (shift next
            (stream-cons el (next))))
        seq)
      stream-null)))

(define stream->list
  (lambda (stream)
    (let f ([stream stream])
      (if (stream-null? stream)
          '()
          (cons (stream-car stream)
                (f (stream-cdr stream)))))))

;;; Part 6: run-with-handler / perform

(define run-with-handler
  (lambda (tag ret-handler eff-handler thunk)
    (ret-handler
     (call-with-continuation-prompt
      thunk
      tag
      (lambda (proc) (proc eff-handler))))))

(define perform
  (lambda (tag val)
    (call-with-composable-continuation
     (lambda (raw-k)
       (abort-current-continuation tag
        (lambda (eff-handler)
          (eff-handler
           (lambda args
             (call-with-continuation-prompt
              (lambda () (apply raw-k args))
              tag
              (lambda (proc) (proc eff-handler))))
           val))))
     tag)))

;;; Helper

(define collect-wind-events
  (lambda (thunk)
    (let ([events '()])
      (define push!
        (lambda (x) (set! events (cons x events))))
      (define get-events
        (lambda () (reverse events)))
      (thunk push! get-events))))

;;; Test infrastructure

(define test-count 0)
(define fail-count 0)

(define do-check
  (lambda (label expected actual-thunk)
    (set! test-count (+ test-count 1))
    (guard (exc [#t
                 (set! fail-count (+ fail-count 1))
                 (display "TEST ")
                 (display label)
                 (display ": ERROR ")
                 (write exc)
                 (newline)])
      (let* ([actual (actual-thunk)]
             [pass? (equal? expected actual)])
        (display "TEST ")
        (display label)
        (display ": ")
        (if pass?
            (display "PASS")
            (begin
              (set! fail-count (+ fail-count 1))
              (display "FAIL expected=")
              (write expected)
              (display " got=")
              (write actual)))
        (newline)))))

(define-syntax test
  (syntax-rules ()
    [(test label expected expr)
     (do-check label expected (lambda () expr))]))

;;; Test suite

(run (lambda ()

(test "shift-reset-basic" 4
  (reset (* 2 (shift k 4))))

(test "shift-reset-apply1" 8
  (reset (* 2 (shift k (k 4)))))

(test "shift-reset-apply2" 16
  (reset (* 2 (shift k (k (k 4))))))

(test "shift-nested" 24
  (reset (* 2 (shift k1 (* 3 (shift k2 (k1 (k2 4))))))))

(test "shift-side-effects" '(1 2)
  (reset
    (begin
      (shift k (cons 1 (k 'void)))
      (shift k (cons 2 (k 'void)))
      '())))

(test "shift-at-basic" 4
  (let ([tag (make-continuation-prompt-tag)])
    (reset-at tag (* 2 (shift-at tag k 4)))))

(test "shift-at-apply" 8
  (let ([tag (make-continuation-prompt-tag)])
    (reset-at tag (* 2 (shift-at tag k (k 4))))))

(test "state-basic-get" '(a b)
  (run-with-state
    (lambda (get put)
      (let ([x (get)])
        (put 'b)
        (list x (get))))
    'a))

(test "state-nested" '(a b c d)
  (run-with-state
    (lambda (get1 put1)
      (run-with-state
        (lambda (get2 put2)
          (let* ([x (get1)]
                 [y (get2)])
            (put1 'c)
            (put2 'd)
            (list x y (get1) (get2))))
        'b))
    'a))

(test "state-accumulate" 10
  (run-with-state
    (lambda (get put)
      (let loop ([i 0])
        (if (= i 5)
            (get)
            (begin
              (put (+ (get) i))
              (loop (+ i 1))))))
    0))

(test "state-amb-scoping" '(1 1)
  (collect-all
    (lambda ()
      (run-with-state
        (lambda (get put)
          (let ([x (amb '(a b))])
            (put (+ (get) 1))
            (get)))
        0))))

(test "amb-basic" '(1 2 3)
  (collect-all
    (lambda ()
      (amb '(1 2 3)))))

(test "amb-filter" '(1 3 5)
  (collect-all
    (lambda ()
      (let ([x (amb '(1 2 3 4 5))])
        (when (even? x) (fail))
        x))))

(test "amb-cartesian" '((1 a) (1 b) (2 a) (2 b))
  (collect-all
    (lambda ()
      (let* ([x (amb '(1 2))]
             [y (amb '(a b))])
        (list x y)))))

(test "amb-empty" '()
  (collect-all
    (lambda ()
      (amb '())
      42)))

(test "amb-pythagorean" '((3 4 5) (4 3 5))
  (collect-all
    (lambda ()
      (let* ([a (amb '(1 2 3 4 5 6 7))]
             [b (amb '(1 2 3 4 5 6 7))]
             [c (amb '(1 2 3 4 5 6 7))])
        (unless (= (+ (* a a) (* b b)) (* c c))
          (fail))
        (list a b c)))))

(test "foreach-stream" '(1 2 3)
  (stream->list (for-each->stream for-each '(1 2 3))))

(test "foreach-stream-partial" 1
  (stream-car (for-each->stream for-each '(1 2 3))))

(test "wind-backtrack" '(in try-1 out in try-2 out)
  (collect-wind-events
    (lambda (push! get-events)
      (collect-all
        (lambda ()
          (let ([x (amb '(1 2))])
            (dynamic-wind
                (lambda () (push! 'in))
                (lambda ()
                  (push! (string->symbol
                           (string-append "try-"
                             (number->string x)))))
                (lambda () (push! 'out))))))
      (get-events))))

(test "handler-return" 84
  (let ([tag (make-continuation-prompt-tag)])
    (run-with-handler tag
      (lambda (v) (* v 2))
      (lambda (k v) (error 'handler "unexpected"))
      (lambda () 42))))

(test "handler-effect" 84
  (let ([tag (make-continuation-prompt-tag)])
    (run-with-handler tag
      (lambda (v) (* v 2))
      (lambda (k v) (k (* v 2)))
      (lambda () (+ (perform tag 20) 2)))))

(test "handler-multi" 10
  (let ([tag (make-continuation-prompt-tag)])
    (run-with-handler tag
      values
      (lambda (k v) (k (+ v 1)))
      (lambda () (+ (perform tag 3) (perform tag 5))))))

(test "handler-abort" 99
  (let ([tag (make-continuation-prompt-tag)])
    (run-with-handler tag
      values
      (lambda (k v) v)
      (lambda () (+ (perform tag 99) 1000)))))

(display "TOTAL: ")
(display test-count)
(display " tests, ")
(display fail-count)
(display " failures")
(newline)

))
SCHEMEEOF
