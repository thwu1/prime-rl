;;; csp.scm --- CSP-style cooperative concurrency for Guile
;;;
;;; Implements cooperative tasks with channels, select, and a
;;; deadlock-detecting scheduler using delimited continuations.
;;;

(define-module (csp)
  #:use-module (srfi srfi-9)
  #:use-module (srfi srfi-1)
  #:use-module (ice-9 q)
  #:export (spawn
            yield!
            task-dead?
            task-result
            make-channel
            channel-send!
            channel-recv!
            channel-close!
            select
            run-scheduler))

;;; ---------------------------------------------------------------------------
;;; Task record
;;; ---------------------------------------------------------------------------

(define-record-type <task>
  (%make-task tag continuation state result)
  task?
  (tag           task-tag)
  (continuation  task-continuation  set-task-continuation!)
  (state         task-state         set-task-state!)
  (result        task-result        set-task-result!))

;;; ---------------------------------------------------------------------------
;;; Channel record
;;; ---------------------------------------------------------------------------

(define-record-type <channel>
  (%make-channel capacity buffer closed? send-waiters recv-waiters)
  channel?
  (capacity      channel-capacity)
  (buffer        channel-buffer      set-channel-buffer!)
  (closed?       channel-closed?     set-channel-closed?!)
  (send-waiters  channel-send-waiters  set-channel-send-waiters!)
  (recv-waiters  channel-recv-waiters  set-channel-recv-waiters!))

;;; ---------------------------------------------------------------------------
;;; Scheduler state (set during run-scheduler)
;;; ---------------------------------------------------------------------------

(define *scheduler-tag*    (make-fluid #f))
(define *current-task*     (make-fluid #f))
(define *enqueue-task!*    (make-fluid #f))

;;; ---------------------------------------------------------------------------
;;; Task state predicates
;;; ---------------------------------------------------------------------------

(define (task-dead? t)
  "Return #t if the task has finished execution."
  (eq? (task-state t) 'dead))

;;; ---------------------------------------------------------------------------
;;; Task creation
;;; ---------------------------------------------------------------------------

(define (spawn thunk)
  "Create a task from THUNK. Returns the task object."
  (let* ((tag (make-prompt-tag 'task))
         (task (%make-task tag #f 'ready #f)))
    ;; Initial continuation wraps thunk with current-task binding
    (set-task-continuation! task
      (lambda (_)
        (with-fluids ((*current-task* task))
          (let ((res (thunk)))
            (set-task-state! task 'dead)
            (set-task-result! task res)
            res))))
    task))

;;; ---------------------------------------------------------------------------
;;; Yield — suspend current task
;;; ---------------------------------------------------------------------------

(define (yield!)
  "Suspend the current task, returning control to the scheduler."
  (let ((task (fluid-ref *current-task*)))
    (unless task
      (error "yield! called outside of a task"))
    ;; Abort to the task's own prompt tag to suspend
    (abort-to-prompt (task-tag task) 'yield task)))

;;; ---------------------------------------------------------------------------
;;; Channel operations — STUBS
;;; ---------------------------------------------------------------------------

(define* (make-channel #:optional (capacity 0))
  "Create a channel. Capacity 0 = synchronous (unbuffered)."
  (%make-channel capacity '() #f '() '()))

(define (channel-send! ch value)
  "Send VALUE on channel CH. Blocks if necessary."
  ;; TODO: implement blocking send with scheduler integration
  (error "channel-send! not implemented"))

(define (channel-recv! ch)
  "Receive a value from channel CH. Blocks if necessary."
  ;; TODO: implement blocking receive with scheduler integration
  (error "channel-recv! not implemented"))

(define (channel-close! ch)
  "Close channel CH."
  ;; TODO: implement close with proper waiter notification
  (error "channel-close! not implemented"))

;;; ---------------------------------------------------------------------------
;;; Select — STUB
;;; ---------------------------------------------------------------------------

(define (select clauses)
  "Block until one of CLAUSES is ready. Each clause is (channel . direction).
   Returns (channel . direction) of the first ready clause."
  ;; TODO: implement select with readiness checking and blocking
  (error "select not implemented"))

;;; ---------------------------------------------------------------------------
;;; Scheduler — STUB
;;; ---------------------------------------------------------------------------

(define (run-scheduler tasks)
  "Run TASKS cooperatively until all complete or deadlock.
   Returns results in completion order."
  ;; TODO: implement cooperative scheduler with:
  ;;   - round-robin run queue
  ;;   - channel-blocked task parking
  ;;   - deadlock detection (all live tasks blocked, no progress possible)
  ;;   - collect results in completion order
  (error "run-scheduler not implemented"))
