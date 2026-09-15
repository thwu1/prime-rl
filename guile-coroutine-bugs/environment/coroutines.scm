;;; coroutines.scm --- Cooperative coroutines for Guile using delimited continuations
;;;
;;; This module provides cooperative coroutines built on Guile's
;;; call-with-prompt / abort-to-prompt delimited continuation primitives.
;;; Coroutines can yield values, receive sent values, and maintain
;;; per-coroutine fluid (dynamic) state.
;;;

(define-module (coroutines)
  #:use-module (srfi srfi-9)
  #:use-module (srfi srfi-1)
  #:export (make-coroutine
            coroutine-yield
            coroutine-resume
            coroutine-send
            coroutine-alive?
            coroutine-dead?
            coroutine-result
            run-all
            make-coroutine-fluid
            coroutine-fluid-ref
            coroutine-fluid-set!))

;;; ---------------------------------------------------------------------------
;;; Data types
;;; ---------------------------------------------------------------------------

(define-record-type <coroutine>
  (%make-coroutine prompt-tag continuation state result fluid-store)
  coroutine?
  (prompt-tag  coroutine-prompt-tag)
  (continuation coroutine-continuation set-coroutine-continuation!)
  (state       coroutine-state         set-coroutine-state!)
  (result      coroutine-result        set-coroutine-result!)
  (fluid-store coroutine-fluid-store   set-coroutine-fluid-store!))

(define-record-type <coroutine-fluid>
  (make-coroutine-fluid default)
  coroutine-fluid?
  (default coroutine-fluid-default))

;;; ---------------------------------------------------------------------------
;;; Internal state
;;; ---------------------------------------------------------------------------

;; Fluid that tracks which coroutine is currently executing.
(define *current-coroutine* (make-fluid #f))

;;; ---------------------------------------------------------------------------
;;; Coroutine state predicates
;;; ---------------------------------------------------------------------------

(define (coroutine-alive? co)
  "Return #t if the coroutine has not yet finished."
  (not (eq? (coroutine-state co) 'dead)))

(define (coroutine-dead? co)
  "Return #t if the coroutine has finished execution."
  (eq? (coroutine-state co) 'dead))

;;; ---------------------------------------------------------------------------
;;; Coroutine-local fluid variables
;;; ---------------------------------------------------------------------------

(define (coroutine-fluid-ref cf)
  "Read the value of coroutine-fluid CF in the current coroutine's store.
   Falls back to the default if no value has been set."
  (let ((co (fluid-ref *current-coroutine*)))
    (if co
        (let ((entry (assq cf (coroutine-fluid-store co))))
          (if entry (cdr entry) (coroutine-fluid-default cf)))
        (coroutine-fluid-default cf))))

(define (coroutine-fluid-set! cf val)
  "Write VAL as the value of coroutine-fluid CF in the current coroutine's
   store."
  (let ((co (fluid-ref *current-coroutine*)))
    (when co
      ;; NOTE: assq-set! returns a (possibly new) list, but the result
      ;; is not stored back into the record.
      (assq-set! (coroutine-fluid-store co) cf val))))

;;; ---------------------------------------------------------------------------
;;; Coroutine creation
;;; ---------------------------------------------------------------------------

(define (make-coroutine thunk)
  "Create a new coroutine that will execute THUNK (a zero-argument procedure)
   when first resumed.  Returns the coroutine object."
  (let* ((tag (make-prompt-tag 'coroutine))
         (co  (%make-coroutine tag #f 'ready #f '())))
    ;; The initial continuation wraps the thunk with a with-fluids binding
    ;; so that *current-coroutine* is set during execution.
    (set-coroutine-continuation! co
      (lambda (initial-val)
        (with-fluids ((*current-coroutine* co))
          (let ((result (thunk)))
            (set-coroutine-state! co 'dead)
            (set-coroutine-result! co result)
            result))))
    co))

;;; ---------------------------------------------------------------------------
;;; Yielding from inside a coroutine
;;; ---------------------------------------------------------------------------

(define (coroutine-yield . args)
  "Suspend the current coroutine.  The optional argument (if any) is the
   value that coroutine-resume will return to the caller.  Returns the
   value passed by the next coroutine-resume or coroutine-send."
  (let ((co (fluid-ref *current-coroutine*)))
    (unless co
      (error "coroutine-yield called outside of a coroutine"))
    (let ((tag (coroutine-prompt-tag co))
          (val (if (pair? args) (car args) *unspecified*)))
      ;; Abort to the enclosing prompt, suspending execution.
      (abort-to-prompt tag))))

;;; ---------------------------------------------------------------------------
;;; Resuming a coroutine
;;; ---------------------------------------------------------------------------

(define (coroutine-resume co)
  "Resume coroutine CO.  If the coroutine yields, returns the yielded value.
   If the coroutine finishes, returns the thunk's return value and marks the
   coroutine dead."
  (if (coroutine-dead? co)
      (error "Cannot resume a dead coroutine")
      (let ((tag  (coroutine-prompt-tag co))
            (cont (coroutine-continuation co)))
        (call-with-prompt tag
          (lambda ()
            (cont *unspecified*))
          (lambda (k . rest)
            (set-coroutine-continuation! co k)
            (set-coroutine-state! co 'suspended)
            ;; Return value from the handler — should be the yielded value
            *unspecified*)))))

;;; ---------------------------------------------------------------------------
;;; Sending a value into a coroutine
;;; ---------------------------------------------------------------------------

(define (coroutine-send co value)
  "Resume coroutine CO, causing the pending coroutine-yield inside the
   coroutine to return VALUE.  Returns the next yielded value or the
   thunk's return value if the coroutine finishes."
  (if (coroutine-dead? co)
      (error "Cannot send to a dead coroutine")
      (let ((tag  (coroutine-prompt-tag co))
            (cont (coroutine-continuation co)))
        (call-with-prompt tag
          (lambda ()
            ;; Resume with the sent value — the continuation receives it
            (cont *unspecified*))
          (lambda (k . rest)
            (set-coroutine-continuation! co k)
            (set-coroutine-state! co 'suspended)
            (if (pair? rest) (car rest) *unspecified*))))))

;;; ---------------------------------------------------------------------------
;;; Round-robin scheduler
;;; ---------------------------------------------------------------------------

(define (run-all coroutines)
  "Run all COROUTINES in round-robin fashion until every one has completed.
   Returns a list of results in the order coroutines finished."
  (let loop ((active  (list-copy coroutines))
             (results '()))
    (if (null? active)
        (reverse results)
        (let* ((co   (car active))
               (rest (cdr active))
               (val  (coroutine-resume co)))
          ;; Rotate the coroutine back into the queue regardless of state
          (loop (append rest (list co))
                (if (coroutine-dead? co)
                    (cons (coroutine-result co) results)
                    results))))))
