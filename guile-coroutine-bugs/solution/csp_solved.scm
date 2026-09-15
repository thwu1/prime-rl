;;; csp.scm --- CSP-style cooperative concurrency for Guile (SOLVED)
;;;

(define-module (csp)
  #:use-module (srfi srfi-9)
  #:use-module (srfi srfi-1)
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

(define (task-dead? t)
  (eq? (task-state t) 'dead))

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
;;; Scheduler state (fluids set during run-scheduler)
;;; ---------------------------------------------------------------------------

(define *scheduler-tag*    (make-fluid #f))
(define *current-task*     (make-fluid #f))
(define *enqueue-task!*    (make-fluid #f))

;;; ---------------------------------------------------------------------------
;;; Task creation
;;; ---------------------------------------------------------------------------

(define (spawn thunk)
  "Create a task from THUNK. Returns the task object."
  (let* ((tag (make-prompt-tag 'task))
         (task (%make-task tag #f 'ready #f)))
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
    (abort-to-prompt (fluid-ref *scheduler-tag*) 'yield task)))

;;; ---------------------------------------------------------------------------
;;; Channel operations
;;; ---------------------------------------------------------------------------

(define* (make-channel #:optional (capacity 0))
  "Create a channel. Capacity 0 = synchronous (unbuffered)."
  (%make-channel capacity '() #f '() '()))

(define (channel-send! ch value)
  "Send VALUE on channel CH. Blocks if necessary."
  (when (channel-closed? ch)
    (throw 'channel-closed "channel is closed"))
  (let ((waiters (channel-recv-waiters ch)))
    (if (pair? waiters)
        ;; A receiver is waiting — hand off value directly
        (let ((waiter (car waiters)))
          (set-channel-recv-waiters! ch (cdr waiters))
          (let ((waiting-task (car waiter))
                (recv-cont    (cdr waiter)))
            (set-task-continuation! waiting-task
              (lambda (_) (with-fluids ((*current-task* waiting-task))
                            (recv-cont value))))
            (set-task-state! waiting-task 'ready)
            ((fluid-ref *enqueue-task!*) waiting-task)))
        ;; No receiver waiting
        (if (and (> (channel-capacity ch) 0)
                 (< (length (channel-buffer ch)) (channel-capacity ch)))
            ;; Buffered and not full — enqueue into buffer
            (set-channel-buffer! ch
              (append (channel-buffer ch) (list value)))
            ;; Must block sender
            (abort-to-prompt (fluid-ref *scheduler-tag*)
                             'blocked-send
                             (fluid-ref *current-task*)
                             ch
                             value)))))

(define (channel-recv! ch)
  "Receive a value from channel CH. Blocks if necessary."
  (let ((buf (channel-buffer ch)))
    (if (pair? buf)
        ;; Buffer has data — take from front
        (let ((value (car buf)))
          (set-channel-buffer! ch (cdr buf))
          ;; If a sender is waiting, move its value into the buffer
          ;; and unblock it
          (let ((sw (channel-send-waiters ch)))
            (when (pair? sw)
              (let* ((waiter (car sw))
                     (stask  (car waiter))
                     (scont  (cadr waiter))
                     (sval   (caddr waiter)))
                (set-channel-send-waiters! ch (cdr sw))
                (set-channel-buffer! ch
                  (append (channel-buffer ch) (list sval)))
                (set-task-continuation! stask
                  (lambda (_) (with-fluids ((*current-task* stask))
                                (scont *unspecified*))))
                (set-task-state! stask 'ready)
                ((fluid-ref *enqueue-task!*) stask))))
          value)
        ;; Buffer empty — check send-waiters (for sync channels)
        (let ((sw (channel-send-waiters ch)))
          (if (pair? sw)
              ;; Sender waiting (synchronous) — take its value directly
              (let* ((waiter (car sw))
                     (stask  (car waiter))
                     (scont  (cadr waiter))
                     (sval   (caddr waiter)))
                (set-channel-send-waiters! ch (cdr sw))
                (set-task-continuation! stask
                  (lambda (_) (with-fluids ((*current-task* stask))
                                (scont *unspecified*))))
                (set-task-state! stask 'ready)
                ((fluid-ref *enqueue-task!*) stask)
                sval)
              ;; No data, no sender
              (if (channel-closed? ch)
                  'channel-closed
                  ;; Block receiver
                  (abort-to-prompt (fluid-ref *scheduler-tag*)
                                   'blocked-recv
                                   (fluid-ref *current-task*)
                                   ch)))))))

(define (channel-close! ch)
  "Close channel CH."
  (set-channel-closed?! ch #t)
  ;; Unblock all waiting senders with error
  (for-each
    (lambda (waiter)
      (let ((stask (car waiter))
            (scont (cadr waiter)))
        (set-task-continuation! stask
          (lambda (_) (with-fluids ((*current-task* stask))
                        (throw 'channel-closed "channel is closed"))))
        (set-task-state! stask 'ready)
        ((fluid-ref *enqueue-task!*) stask)))
    (channel-send-waiters ch))
  (set-channel-send-waiters! ch '())
  ;; Unblock all waiting receivers with sentinel
  (for-each
    (lambda (waiter)
      (let ((rtask (car waiter))
            (rcont (cdr waiter)))
        (set-task-continuation! rtask
          (lambda (_) (with-fluids ((*current-task* rtask))
                        (rcont 'channel-closed))))
        (set-task-state! rtask 'ready)
        ((fluid-ref *enqueue-task!*) rtask)))
    (channel-recv-waiters ch))
  (set-channel-recv-waiters! ch '()))

;;; ---------------------------------------------------------------------------
;;; Select
;;; ---------------------------------------------------------------------------

(define (channel-recv-ready? ch)
  "True if a recv on CH would not block."
  (or (pair? (channel-buffer ch))
      (pair? (channel-send-waiters ch))
      (channel-closed? ch)))

(define (channel-send-ready? ch)
  "True if a send on CH would not block."
  (or (pair? (channel-recv-waiters ch))
      (and (> (channel-capacity ch) 0)
           (< (length (channel-buffer ch)) (channel-capacity ch)))))

(define (select clauses)
  "Block until one of CLAUSES is ready. Returns (channel . direction)."
  (let ((ready (find (lambda (clause)
                       (let ((ch  (car clause))
                             (dir (cdr clause)))
                         (case dir
                           ((recv) (channel-recv-ready? ch))
                           ((send) (channel-send-ready? ch))
                           (else #f))))
                     clauses)))
    (if ready
        ready
        (begin
          (yield!)
          (select clauses)))))

;;; ---------------------------------------------------------------------------
;;; Scheduler
;;; ---------------------------------------------------------------------------

(define (run-scheduler tasks)
  "Run TASKS cooperatively until all complete or deadlock."
  (let ((sched-tag (make-prompt-tag 'scheduler))
        (run-queue '())
        (results '()))

    (define (enqueue! task)
      (set! run-queue (append run-queue (list task))))

    (define (dequeue!)
      (if (null? run-queue)
          #f
          (let ((task (car run-queue)))
            (set! run-queue (cdr run-queue))
            task)))

    (define (run-task task)
      (let ((cont (task-continuation task)))
        (call-with-prompt sched-tag
          (lambda ()
            (with-fluids ((*scheduler-tag* sched-tag)
                          (*current-task* task)
                          (*enqueue-task!* enqueue!))
              (cont *unspecified*)))
          (lambda (k reason . args)
            (handle-abort k reason args)))))

    (define (handle-abort k reason args)
      (case reason
        ((yield)
         (let ((task (car args)))
           (set-task-continuation! task k)
           (set-task-state! task 'suspended)
           (enqueue! task)))

        ((blocked-send)
         (let ((task (car args))
               (ch   (cadr args))
               (val  (caddr args)))
           (set-task-continuation! task k)
           (set-task-state! task 'blocked)
           (set-channel-send-waiters! ch
             (append (channel-send-waiters ch)
                     (list (list task k val))))))

        ((blocked-recv)
         (let ((task (car args))
               (ch   (cadr args)))
           (set-task-continuation! task k)
           (set-task-state! task 'blocked)
           (set-channel-recv-waiters! ch
             (append (channel-recv-waiters ch)
                     (list (cons task k))))))))

    ;; Seed the run queue
    (for-each enqueue! tasks)
    (let ((total-tasks (length tasks)))

      ;; Main scheduler loop
      (let loop ()
        (let ((task (dequeue!)))
          (cond
            (task
             (run-task task)
             (when (task-dead? task)
               (set! results (append results (list (task-result task)))))
             (loop))

            ;; All tasks completed
            ((= (length results) total-tasks)
             results)

            ;; Run queue empty but tasks remain — deadlock
            (else
             (throw 'deadlock "all tasks are blocked"))))))))
