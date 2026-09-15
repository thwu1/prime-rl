#lang racket

;; CIS531 Fall '25 Project 5 — Complete Solution
;; Compiling Functions (R4/5) -> x86-64
(require "irs.rkt")
(require "system.rkt")
(provide (all-defined-out))

;; ======================================================================
;; Pass 1: shrink — desugar to core forms
;; ======================================================================
(define (shrink p)
  (define (h e)
    (match e
      [(? fixnum? n) n]
      [(? boolean? b) b]
      [(? symbol? x) x]
      ['(read) '(read)]
      ['(void) '(void)]
      [`(- ,e0) `(- ,(h e0))]
      [`(- ,e0 ,e1) `(+ ,(h e0) (- ,(h e1)))]
      [`(+ ,e0 ,e1) `(+ ,(h e0) ,(h e1))]
      [`(not ,e0) `(not ,(h e0))]
      [`(and ,e0 ,e1) `(if ,(h e0) ,(h e1) #f)]
      [`(or ,e0 ,e1)
       (define t (gensym 'or))
       `(let ([,t ,(h e0)]) (if ,t ,t ,(h e1)))]
      [`(eq? ,e0 ,e1) `(eq? ,(h e0) ,(h e1))]
      [`(< ,e0 ,e1) `(< ,(h e0) ,(h e1))]
      [`(<= ,e0 ,e1)
       (define a (gensym 'a)) (define b (gensym 'b))
       `(let ([,a ,(h e0)]) (let ([,b ,(h e1)]) (if (eq? ,a ,b) #t (< ,a ,b))))]
      [`(> ,e0 ,e1) `(< ,(h e1) ,(h e0))]
      [`(>= ,e0 ,e1) (h `(<= ,e1 ,e0))]
      [`(if ,g ,t ,f) `(if ,(h g) ,(h t) ,(h f))]
      [`(let ([,x ,e]) ,eb) `(let ([,x ,(h e)]) ,(h eb))]
      [`(let* () ,eb) (h eb)]
      [`(let* ([,x ,e] ,rest ...) ,eb)
       `(let ([,x ,(h e)]) ,(h `(let* ,rest ,eb)))]
      [`(begin ,e) (h e)]
      [`(begin ,e ,rest ...)
       `(let ([_ ,(h e)]) ,(h `(begin ,@rest)))]
      [`(while ,g ,body ...)
       (define b (if (= (length body) 1) (h (first body)) (h `(begin ,@body))))
       `(let ([_ (while ,(h g) ,b)]) (void))]
      [`(make-vector ,e) `(make-vector ,(h e))]
      [`(vector-ref ,e ,i) `(vector-ref ,(h e) ,i)]
      [`(vector-set! ,e ,i ,ev) `(vector-set! ,(h e) ,i ,(h ev))]
      [`(set! ,x ,e) `(set! ,x ,(h e))]
      [`(lambda (,xs ...) ,eb) `(lambda ,xs ,(h eb))]
      [`(,ef ,eargs ...) `(,(h ef) ,@(map h eargs))]))
  (define (per-defn d)
    (match d [`(define (,f ,xs ...) ,eb) `(define (,f ,@xs) ,(h eb))]))
  (match p
    [`(program ,defns ... ,expr)
     `(program ,@(cons `(define (,(entry-symbol)) ,(h expr)) (map per-defn defns)))]))

;; ======================================================================
;; Pass 2: uniqueify — alpha-rename bound variables
;; ======================================================================
(define (uniqueify p)
  (define (rename e env)
    (match e
      [(? fixnum? n) n]
      [(? boolean? b) b]
      ['(read) '(read)]
      ['(void) '(void)]
      [(? symbol? x) (hash-ref env x x)]
      [`(- ,e0) `(- ,(rename e0 env))]
      [`(+ ,e0 ,e1) `(+ ,(rename e0 env) ,(rename e1 env))]
      [`(not ,e0) `(not ,(rename e0 env))]
      [`(,(? shrunk-cmp? c) ,e0 ,e1) `(,c ,(rename e0 env) ,(rename e1 env))]
      [`(if ,g ,t ,f) `(if ,(rename g env) ,(rename t env) ,(rename f env))]
      [`(let ([_ (while ,g ,b)]) ,r)
       `(let ([_ (while ,(rename g env) ,(rename b env))]) ,(rename r env))]
      [`(let ([_ ,rhs]) ,body)
       `(let ([_ ,(rename rhs env)]) ,(rename body env))]
      [`(let ([,(? symbol? x) ,rhs]) ,body)
       (define x+ (gensym x))
       `(let ([,x+ ,(rename rhs env)]) ,(rename body (hash-set env x x+)))]
      [`(make-vector ,e) `(make-vector ,(rename e env))]
      [`(vector-ref ,e ,i) `(vector-ref ,(rename e env) ,i)]
      [`(vector-set! ,e ,i ,v) `(vector-set! ,(rename e env) ,i ,(rename v env))]
      [`(set! ,(? symbol? x) ,e) `(set! ,(hash-ref env x x) ,(rename e env))]
      [`(lambda (,xs ...) ,eb)
       (define nxs (map gensym xs))
       (define env+ (foldl (lambda (o n a) (hash-set a o n)) env xs nxs))
       `(lambda ,nxs ,(rename eb env+))]
      [`(,ef ,eargs ...) `(,(rename ef env) ,@(map (lambda (a) (rename a env)) eargs))]))
  (define (per-defn d)
    (match d
      [`(define (,f ,xs ...) ,eb)
       (define nxs (map gensym xs))
       (define env (foldl (lambda (o n a) (hash-set a o n)) (hash) xs nxs))
       `(define (,f ,@nxs) ,(rename eb env))]))
  (match p [`(program ,defns ...) `(program ,@(map per-defn defns))]))

;; ======================================================================
;; Pass 3: reveal-functions — mark function refs and wrap calls in app
;; ======================================================================
(define (reveal-functions p)
  (define (walk e fns)
    (match e
      [(? fixnum? n) n]
      [(? boolean? b) b]
      ['(read) '(read)]
      ['(void) '(void)]
      [(? symbol? x) (if (set-member? fns x) `(fun-ref ,x) x)]
      [`(- ,e0) `(- ,(walk e0 fns))]
      [`(+ ,e0 ,e1) `(+ ,(walk e0 fns) ,(walk e1 fns))]
      [`(not ,e0) `(not ,(walk e0 fns))]
      [`(,(? shrunk-cmp? c) ,e0 ,e1) `(,c ,(walk e0 fns) ,(walk e1 fns))]
      [`(if ,g ,t ,f) `(if ,(walk g fns) ,(walk t fns) ,(walk f fns))]
      [`(let ([_ (while ,g ,b)]) ,r)
       `(let ([_ (while ,(walk g fns) ,(walk b fns))]) ,(walk r fns))]
      [`(let ([_ ,rhs]) ,body) `(let ([_ ,(walk rhs fns)]) ,(walk body fns))]
      [`(let ([,(? symbol? x) ,rhs]) ,body)
       `(let ([,x ,(walk rhs fns)]) ,(walk body fns))]
      [`(make-vector ,e) `(make-vector ,(walk e fns))]
      [`(vector-ref ,e ,i) `(vector-ref ,(walk e fns) ,i)]
      [`(vector-set! ,e ,i ,v) `(vector-set! ,(walk e fns) ,i ,(walk v fns))]
      [`(set! ,x ,e) `(set! ,x ,(walk e fns))]
      [`(lambda (,xs ...) ,eb) `(lambda ,xs ,(walk eb fns))]
      [`(,ef ,eargs ...) `(app ,(walk ef fns) ,@(map (lambda (a) (walk a fns)) eargs))]))
  (match p
    [`(program ,defns ...)
     (define fns (list->set (map (lambda (d) (match d [`(define (,f ,_ ...) ,_) f])) defns)))
     `(program ,@(map (lambda (d) (match d [`(define (,f ,xs ...) ,eb)
                                             `(define (,f ,@xs) ,(walk eb fns))])) defns))]))

;; ======================================================================
;; Pass 4: assignment-convert — box mutated variables
;; ======================================================================
(define (assignment-convert p)
  (define (box-formals genfs realfs body)
    (match genfs
      ['() body]
      [`(,x . ,rst)
       `(let ([,(first realfs) (make-vector 1)])
          (let ([_ (vector-set! ,(first realfs) 0 ,x)])
            ,(box-formals rst (rest realfs) body)))]))

  (define (collect-set! e)
    (match e
      [(? fixnum?) (set)] [(? boolean?) (set)] [(? symbol?) (set)]
      ['(read) (set)] ['(void) (set)] [`(fun-ref ,_) (set)]
      [`(- ,e0) (collect-set! e0)]
      [`(+ ,e0 ,e1) (set-union (collect-set! e0) (collect-set! e1))]
      [`(not ,e0) (collect-set! e0)]
      [`(,(? shrunk-cmp?) ,e0 ,e1) (set-union (collect-set! e0) (collect-set! e1))]
      [`(if ,g ,t ,f) (set-union (collect-set! g) (collect-set! t) (collect-set! f))]
      [`(let ([_ (while ,g ,b)]) ,r) (set-union (collect-set! g) (collect-set! b) (collect-set! r))]
      [`(let ([,_ ,e]) ,b) (set-union (collect-set! e) (collect-set! b))]
      [`(make-vector ,e) (collect-set! e)]
      [`(vector-ref ,e ,_) (collect-set! e)]
      [`(vector-set! ,e ,_ ,v) (set-union (collect-set! e) (collect-set! v))]
      [`(set! ,x ,e) (set-add (collect-set! e) x)]
      [`(app ,es ...) (apply set-union (set) (map collect-set! es))]
      [`(lambda (,xs ...) ,e) (collect-set! e)]
      [_ (set)]))

  (define (a-c e muts)
    (match e
      [(? fixnum?) e] [(? boolean?) e] ['(read) e] ['(void) e] [`(fun-ref ,_) e]
      [(? symbol? x) (if (set-member? muts x) `(vector-ref ,x 0) x)]
      [`(- ,e0) `(- ,(a-c e0 muts))]
      [`(+ ,e0 ,e1) `(+ ,(a-c e0 muts) ,(a-c e1 muts))]
      [`(not ,e0) `(not ,(a-c e0 muts))]
      [`(,(? shrunk-cmp? c) ,e0 ,e1) `(,c ,(a-c e0 muts) ,(a-c e1 muts))]
      [`(if ,g ,t ,f) `(if ,(a-c g muts) ,(a-c t muts) ,(a-c f muts))]
      [`(let ([_ (while ,g ,b)]) ,r)
       `(let ([_ (while ,(a-c g muts) ,(a-c b muts))]) ,(a-c r muts))]
      [`(let ([_ ,rhs]) ,body) `(let ([_ ,(a-c rhs muts)]) ,(a-c body muts))]
      [`(let ([,(? symbol? x) ,rhs]) ,body)
       (if (set-member? muts x)
           `(let ([,x (make-vector 1)])
              (let ([_ (vector-set! ,x 0 ,(a-c rhs muts))])
                ,(a-c body muts)))
           `(let ([,x ,(a-c rhs muts)]) ,(a-c body muts)))]
      [`(make-vector ,e) `(make-vector ,(a-c e muts))]
      [`(vector-ref ,e ,i) `(vector-ref ,(a-c e muts) ,i)]
      [`(vector-set! ,e ,i ,v) `(vector-set! ,(a-c e muts) ,i ,(a-c v muts))]
      [`(set! ,x ,e) `(vector-set! ,x 0 ,(a-c e muts))]
      [`(app ,es ...) `(app ,@(map (lambda (e) (a-c e muts)) es))]
      [`(lambda (,xs ...) ,eb)
       (define lm (set-union muts (collect-set! eb)))
       (define mxs (filter (lambda (x) (set-member? lm x)) xs))
       (if (empty? mxs)
           `(lambda ,xs ,(a-c eb lm))
           (let* ([nxs (map (lambda (x) (if (set-member? lm x) (gensym x) x)) xs)]
                  [gm (for/list ([o xs] [n nxs] #:when (set-member? lm o)) n)]
                  [rm mxs])
             `(lambda ,nxs ,(box-formals gm rm (a-c eb lm)))))]))

  (define (per-defn d)
    (match d
      [`(define (,fn ,fs ...) ,eb)
       (define muts (collect-set! eb))
       (define mfs (filter (lambda (f) (set-member? muts f)) fs))
       (if (empty? mfs)
           `(define (,fn ,@fs) ,(a-c eb muts))
           (let* ([nfs (map (lambda (f) (if (set-member? muts f) (gensym f) f)) fs)]
                  [gm (for/list ([o fs] [n nfs] #:when (set-member? muts o)) n)]
                  [rm mfs])
             `(define (,fn ,@nfs) ,(box-formals gm rm (a-c eb muts)))))]))
  (match p [`(program ,defns ...) `(program ,@(map per-defn defns))]))

;; ======================================================================
;; Pass 5: lift-lambdas — closure conversion
;; ======================================================================
(define (lift-lambdas p)
  (define emitted-defines '())
  (define (emit-define! d) (set! emitted-defines (cons d emitted-defines)))

  (define (free-vars e)
    (match e
      [(? fixnum?) (set)] [(? boolean?) (set)] ['(void) (set)] ['(read) (set)]
      [`(fun-ref ,_) (set)] [(? symbol? x) (set x)]
      [`(- ,e+) (free-vars e+)]
      [`(+ ,e0 ,e1) (set-union (free-vars e0) (free-vars e1))]
      [`(not ,e) (free-vars e)]
      [`(,(? cmp? c) ,e0 ,e1) (set-union (free-vars e0) (free-vars e1))]
      [`(and ,e0 ,e1) (set-union (free-vars e0) (free-vars e1))]
      [`(or ,e0 ,e1) (set-union (free-vars e0) (free-vars e1))]
      [`(if ,e0 ,e1 ,e2) (set-union (free-vars e0) (free-vars e1) (free-vars e2))]
      [`(let ([_ (while ,g ,b)]) ,r) (set-union (free-vars g) (free-vars b) (free-vars r))]
      [`(let ([,x ,e]) ,eb) (set-union (free-vars e) (set-remove (free-vars eb) x))]
      [`(make-vector ,i) (if (symbol? i) (set i) (set))]
      [`(vector-ref ,e ,i) (free-vars e)]
      [`(vector-set! ,e ,i ,ev) (set-union (free-vars e) (free-vars ev))]
      [`(set! ,x ,e) (set-union (set x) (free-vars e))]
      [`(lambda (,xs ...) ,e) (foldl (lambda (x a) (set-remove a x)) (free-vars e) xs)]
      [`(app ,ef ,eargs ...) (foldl (lambda (s a) (set-union s a)) (free-vars ef) (map free-vars eargs))]
      [_ (set)]))

  (define (walk e)
    (match e
      [(? fixnum?) e] [(? boolean?) e] ['(read) e] ['(void) e] [(? symbol?) e]
      [`(- ,e0) `(- ,(walk e0))]
      [`(+ ,e0 ,e1) `(+ ,(walk e0) ,(walk e1))]
      [`(not ,e0) `(not ,(walk e0))]
      [`(,(? shrunk-cmp? c) ,e0 ,e1) `(,c ,(walk e0) ,(walk e1))]
      [`(if ,g ,t ,f) `(if ,(walk g) ,(walk t) ,(walk f))]
      [`(let ([_ (while ,g ,b)]) ,r)
       `(let ([_ (while ,(walk g) ,(walk b))]) ,(walk r))]
      [`(let ([_ ,rhs]) ,body) `(let ([_ ,(walk rhs)]) ,(walk body))]
      [`(let ([,(? symbol? x) ,rhs]) ,body) `(let ([,x ,(walk rhs)]) ,(walk body))]
      [`(make-vector ,e) `(make-vector ,(walk e))]
      [`(vector-ref ,e ,i) `(vector-ref ,(walk e) ,i)]
      [`(vector-set! ,e ,i ,v) `(vector-set! ,(walk e) ,i ,(walk v))]
      [`(set! ,x ,e) `(set! ,x ,(walk e))]
      ;; fun-ref: wrap in a 1-element closure [fun-ptr]
      [`(fun-ref ,f)
       (define v (gensym 'v))
       `(let ([,v (make-vector 1)])
          (let ([_ (vector-set! ,v 0 (fun-ref ,f))]) ,v))]
      ;; lambda: lift to top-level with env param
      [`(lambda (,xs ...) ,ebody)
       (define body+ (walk ebody))
       (define fvs (set->list (foldl (lambda (x a) (set-remove a x)) (free-vars body+) xs)))
       (define fname (gensym 'lambda))
       ;; build let-stack to unpack free vars from env vector
       (define (letstack vars i bd)
         (if (null? vars) bd
             `(let ([,(car vars) (vector-ref env ,(+ i 1))])
                ,(letstack (cdr vars) (+ i 1) bd))))
       (emit-define! `(define (,fname env ,@xs) ,(letstack fvs 0 body+)))
       ;; allocate closure: [fun-ref, fv0, fv1, ...]
       (define clo (gensym 'clo))
       (define (fill-clo fvs i)
         (if (null? fvs) clo
             `(let ([_ (vector-set! ,clo ,(+ i 1) ,(car fvs))])
                ,(fill-clo (cdr fvs) (+ i 1)))))
       `(let ([,clo (make-vector ,(+ 1 (length fvs)))])
          (let ([_ (vector-set! ,clo 0 (fun-ref ,fname))])
            ,(fill-clo fvs 0)))]
      ;; application: extract fptr from closure, pass closure as env
      [`(app ,ef ,eargs ...)
       (define ef+ (walk ef))
       (define eargs+ (map walk eargs))
       (define ft (gensym 'f))
       (define fp (gensym 'fp))
       `(let ([,ft ,ef+])
          (let ([,fp (vector-ref ,ft 0)])
            (app ,fp ,ft ,@eargs+)))]))

  (define (per-defn d)
    (match d
      [`(define (,fn ,fs ...) ,eb)
       (define menv (if (equal? fn (entry-symbol)) '() '(env)))
       `(define (,fn ,@menv ,@fs) ,(walk eb))]))
  (match p
    [`(program ,defns ...)
     `(program ,@(map per-defn defns) ,@emitted-defines)]))

;; ======================================================================
;; Pass 6: limit-functions — pack >6 args into a vector
;; ======================================================================
(define (limit-functions p)
  (define maxargs (length (argument-registers-list)))
  (define (walk-expr e)
    (match e
      [(? fixnum?) e] [(? boolean?) e] ['(read) e] ['(void) e]
      [(? symbol?) e] [`(fun-ref ,_) e]
      [`(- ,e0) `(- ,(walk-expr e0))]
      [`(+ ,e0 ,e1) `(+ ,(walk-expr e0) ,(walk-expr e1))]
      [`(not ,e0) `(not ,(walk-expr e0))]
      [`(,(? shrunk-cmp? c) ,e0 ,e1) `(,c ,(walk-expr e0) ,(walk-expr e1))]
      [`(if ,g ,t ,f) `(if ,(walk-expr g) ,(walk-expr t) ,(walk-expr f))]
      [`(let ([_ (while ,g ,b)]) ,r)
       `(let ([_ (while ,(walk-expr g) ,(walk-expr b))]) ,(walk-expr r))]
      [`(let ([_ ,rhs]) ,body) `(let ([_ ,(walk-expr rhs)]) ,(walk-expr body))]
      [`(let ([,(? symbol? x) ,rhs]) ,body) `(let ([,x ,(walk-expr rhs)]) ,(walk-expr body))]
      [`(make-vector ,e) `(make-vector ,(walk-expr e))]
      [`(vector-ref ,e ,i) `(vector-ref ,(walk-expr e) ,i)]
      [`(vector-set! ,e ,i ,v) `(vector-set! ,(walk-expr e) ,i ,(walk-expr v))]
      [`(set! ,x ,e) `(set! ,x ,(walk-expr e))]
      [`(app ,ef ,eargs ...)
       (define ef+ (walk-expr ef))
       (define eargs+ (map walk-expr eargs))
       (if (> (length eargs+) maxargs)
           (let* ([first-a (take eargs+ (- maxargs 1))]
                  [rest-a (drop eargs+ (- maxargs 1))]
                  [v (gensym 'vec)])
             (define (fill as i)
               (if (null? as)
                   `(app ,ef+ ,@first-a ,v)
                   `(let ([_ (vector-set! ,v ,i ,(car as))])
                      ,(fill (cdr as) (+ i 1)))))
             `(let ([,v (make-vector ,(length rest-a))]) ,(fill rest-a 0)))
           `(app ,ef+ ,@eargs+))]))
  (define (per-defn d)
    (match d
      [`(define (,fn ,a0 ,a1 ,a2 ,a3 ,a4 ,a5 ,arest ...) ,eb)
       (define vf (gensym 'rest))
       (define extras (cons a5 arest))
       (define (unpack vs i)
         (if (null? vs) (walk-expr eb)
             `(let ([,(car vs) (vector-ref ,vf ,i)]) ,(unpack (cdr vs) (+ i 1)))))
       `(define (,fn ,a0 ,a1 ,a2 ,a3 ,a4 ,vf) ,(unpack extras 0))]
      [`(define (,fn ,fs ...) ,eb) `(define (,fn ,@fs) ,(walk-expr eb))]))
  (match p [`(program ,ds ...) `(program ,@(map per-defn ds))]))

;; ======================================================================
;; Pass 7: anf-convert — A-Normal Form
;; ======================================================================
(define (anf-convert p)
  (define (convert e k)
    (match e
      [(? fixnum? n) (k n)]
      [(? boolean? b) (k b)]
      [(? symbol? x) (k x)]
      ['(read) (let ([t (gensym 'r)]) `(let ([,t (read)]) ,(k t)))]
      ['(void) (k '(void))]
      [`(- ,e0) (convert e0 (lambda (a) (let ([t (gensym 't)]) `(let ([,t (- ,a)]) ,(k t)))))]
      [`(+ ,e0 ,e1)
       (convert e0 (lambda (a0) (convert e1 (lambda (a1)
         (let ([t (gensym 't)]) `(let ([,t (+ ,a0 ,a1)]) ,(k t)))))))]
      [`(not ,e0) (convert e0 (lambda (a) (let ([t (gensym 't)]) `(let ([,t (not ,a)]) ,(k t)))))]
      [`(,(? shrunk-cmp? c) ,e0 ,e1)
       (convert e0 (lambda (a0) (convert e1 (lambda (a1)
         (let ([t (gensym 't)]) `(let ([,t (,c ,a0 ,a1)]) ,(k t)))))))]
      [`(if ,g ,t ,f)
       (convert g (lambda (ag) `(if ,ag ,(convert t k) ,(convert f k))))]
      [`(let ([_ (while ,g ,b)]) ,r)
       `(let ([_ (while ,(convert g (lambda (x) x)) ,(convert b (lambda (x) x)))])
          ,(convert r k))]
      [`(let ([_ ,rhs]) ,body)
       (convert rhs (lambda (_r) (convert body k)))]
      [`(let ([,(? symbol? x) ,rhs]) ,body)
       (convert rhs (lambda (ar) `(let ([,x ,ar]) ,(convert body k))))]
      [`(make-vector ,e)
       (convert e (lambda (a) (let ([t (gensym 't)]) `(let ([,t (make-vector ,a)]) ,(k t)))))]
      [`(vector-ref ,e ,i)
       (convert e (lambda (a) (let ([t (gensym 't)]) `(let ([,t (vector-ref ,a ,i)]) ,(k t)))))]
      [`(vector-set! ,e ,i ,v)
       (convert e (lambda (ae) (convert v (lambda (av)
         `(let ([_ (vector-set! ,ae ,i ,av)]) ,(k '(void)))))))]
      [`(set! ,x ,e) (convert e (lambda (a) `(let ([_ (set! ,x ,a)]) ,(k '(void)))))]
      [`(fun-ref ,f) (let ([t (gensym 't)]) `(let ([,t (fun-ref ,f)]) ,(k t)))]
      [`(app ,ef ,eargs ...)
       (define (handle-rest es as)
         (if (null? es)
             (let ([t (gensym 't)]) `(let ([,t (app ,@(reverse as))]) ,(k t)))
             (convert (car es) (lambda (a) (handle-rest (cdr es) (cons a as))))))
       (convert ef (lambda (af) (handle-rest eargs (list af))))]))
  (define (per-defn d)
    (match d [`(define (,fn ,fs ...) ,eb) `(define (,fn ,@fs) ,(convert eb (lambda (x) x)))]))
  (match p [`(program ,ds ...) `(program ,@(map per-defn ds))]))

;; ======================================================================
;; Pass 8: explicate-control — generate basic blocks
;; ======================================================================
(define (explicate-control p)
  (define (merge h0 h1) (foldl (lambda (k h) (hash-set h k (hash-ref h0 k))) h1 (hash-keys h0)))
  (define (atom? a) (or (fixnum? a) (symbol? a) (boolean? a) (equal? a '(void))))
  (define (extend h lbl instr) (hash-set h lbl `(seq ,instr ,(hash-ref h lbl))))

  (define (e->b e cb k)
    (match e
      [(? atom? a) (hash cb (k a))]
      [`(if ,(? atom? g) ,et ,ef)
       (define lt (gensym 'then)) (define lf (gensym 'else))
       (define bt (e->b et lt k)) (define bf (e->b ef lf k))
       (hash-set (merge bt bf) cb `(if (eq? ,g #f) (goto ,lf) (goto ,lt)))]
      [`(let ([_ (while ,g ,b)]) ,r)
       (define hd (gensym 'whd)) (define bd (gensym 'wbd)) (define rl (gensym 'wrest))
       (define br (e->b r rl k))
       (define bb (e->b b bd (lambda (_a) `(goto ,hd))))
       (define bg (e->b g hd (lambda (ag) `(if (eq? ,ag #f) (goto ,rl) (goto ,bd)))))
       (hash-set (merge br (merge bb bg)) cb `(goto ,hd))]
      [`(let ([_ (vector-set! ,(? atom? v) ,(? fixnum? i) ,(? atom? val))]) ,rest)
       (extend (e->b rest cb k) cb `(vector-set! ,v ,i ,val))]
      [`(let ([_ ,rhs]) ,rest)
       ;; side-effect let — convert rhs, discard result
       (define t (gensym 'se))
       (extend (e->b rest cb k) cb `(assign ,t ,rhs))]
      [`(let ([,(? symbol? x) ,rhs]) ,rest)
       (extend (e->b rest cb k) cb `(assign ,x ,rhs))]))

  (define (per-defn d)
    (match d [`(define (,fn ,fs ...) ,eb)
              `(define (,fn ,@fs) ,(e->b eb fn (lambda (a) `(return ,a))))]))
  (match p [`(program ,ds ...) `(program ,@(map per-defn ds))]))

;; ======================================================================
;; Pass 9: uncover-locals (provided)
;; ======================================================================
(define (uncover-locals p)
  (define (h seq)
    (match seq
      [`(return ,_) (set)]
      [`(goto ,l) (set)]
      [`(if (,cmp ,a0 ,a1) (goto ,l0) (goto ,l1)) (set)]
      [`(set! ,_ ,_) (set)]
      [`(seq (vector-set! ,x ,_ ,_) ,rest) (set-add (h rest) x)]
      [`(seq (assign ,x0 ,_) ,rest) (set-add (h rest) x0)]))
  (define (per-defn d)
    (match d
      [`(define (,fn ,fs ...) ,blocks)
       (define locals (set-union (list->set fs)
                                 (foldl (lambda (b acc) (set-union acc (h (hash-ref blocks b))))
                                        (set) (hash-keys blocks))))
       `(define ,locals (,fn ,@fs) ,blocks)]))
  (match p [`(program ,ds ...) `(program ,@(map per-defn ds))]))

;; ======================================================================
;; Pass 10: select-instructions — lower to pseudo-x86
;; ======================================================================
(define (select-instructions p)
  (define (c1->block c1)
    (define (ha a)
      (match a
        ['(void)       `(imm ,(void-magic-value))]
        [(? fixnum? n) `(imm ,n)]
        [(? symbol? x) `(var ,x)]
        [(? boolean? b) `(imm ,(if b 1 0))]))
    (define (h seq)
      (match seq
        [`(return ,a)
         `((movq ,(ha a) (reg rax)) (jmp ,(conclusion-block-name)))]
        [`(goto ,l) `((jmp ,l))]
        [`(if (eq? ,a0 ,a1) (goto ,lt) (goto ,lf))
         `((cmpq ,(ha a1) ,(ha a0)) (jmp-if e ,lt) (jmp ,lf))]
        [`(if (< ,a0 ,a1) (goto ,lt) (goto ,lf))
         `((cmpq ,(ha a1) ,(ha a0)) (jmp-if l ,lt) (jmp ,lf))]
        [`(seq (vector-set! ,v ,(? fixnum? i) ,val) ,rest)
         `((movq ,(ha v) (reg r11))
           (movq ,(ha val) (reg rax))
           (movq (reg rax) (deref (reg r11) ,(+ 8 (* i 8))))
           ,@(h rest))]
        [`(seq (assign ,x (read)) ,rest)
         `((callq read_int64 0) (movq (reg rax) (var ,x)) ,@(h rest))]
        [`(seq (assign ,x (void)) ,rest)
         `((movq (imm ,(void-magic-value)) (var ,x)) ,@(h rest))]
        [`(seq (assign ,x ,(? fixnum? n)) ,rest)
         `((movq (imm ,n) (var ,x)) ,@(h rest))]
        [`(seq (assign ,x ,(? boolean? b)) ,rest)
         `((movq (imm ,(if b 1 0)) (var ,x)) ,@(h rest))]
        [`(seq (assign ,x ,(? symbol? y)) ,rest)
         `((movq (var ,y) (var ,x)) ,@(h rest))]
        [`(seq (assign ,x (+ ,a0 ,a1)) ,rest)
         `((movq ,(ha a0) (var ,x)) (addq ,(ha a1) (var ,x)) ,@(h rest))]
        [`(seq (assign ,x (- ,a0)) ,rest)
         `((movq ,(ha a0) (var ,x)) (negq (var ,x)) ,@(h rest))]
        [`(seq (assign ,x (not ,a0)) ,rest)
         `((movq ,(ha a0) (var ,x)) (xorq (imm 1) (var ,x)) ,@(h rest))]
        [`(seq (assign ,x (eq? ,a0 ,a1)) ,rest)
         `((cmpq ,(ha a1) ,(ha a0)) (set e (byte-reg al)) (movzbq (byte-reg al) (var ,x)) ,@(h rest))]
        [`(seq (assign ,x (< ,a0 ,a1)) ,rest)
         `((cmpq ,(ha a1) ,(ha a0)) (set l (byte-reg al)) (movzbq (byte-reg al) (var ,x)) ,@(h rest))]
        [`(seq (assign ,x (make-vector ,n)) ,rest)
         `((movq ,(ha n) (reg rdi)) (callq make_vector 0) (movq (reg rax) (var ,x)) ,@(h rest))]
        [`(seq (assign ,x (vector-ref ,v ,(? fixnum? i))) ,rest)
         `((movq ,(ha v) (reg r11))
           (movq (deref (reg r11) ,(+ 8 (* i 8))) (var ,x))
           ,@(h rest))]
        [`(seq (assign ,x (fun-ref ,f)) ,rest)
         `((leaq (fun-ref ,f) (var ,x)) ,@(h rest))]
        [`(seq (assign ,lhs (app ,af ,args ...)) ,next)
         (define (copy-args as rs)
           (if (null? as) '()
               (cons `(movq ,(ha (car as)) (reg ,(car rs)))
                     (copy-args (cdr as) (cdr rs)))))
         `(,@(copy-args args (argument-registers-list))
           (indirect-callq ,(ha af))
           (movq (reg rax) (var ,lhs))
           ,@(h next))]))
    (h c1))

  (define (per-defn d)
    (match-define `(define ,locals (,f ,args ...) ,blocks) d)
    (define blocks+
      (foldl (lambda (k acc) (hash-set acc k (c1->block (hash-ref blocks k))))
             (hash) (hash-keys blocks)))
    (define blocks++ (hash-set blocks+ (conclusion-block-name) '((retq))))
    (define move-seq
      (for/list ([arg args] [reg (argument-registers-list)]
                 #:when #t)
        `(movq (reg ,reg) (var ,arg))))
    (define entry (hash-ref blocks++ f))
    (define blocks+++ (hash-set blocks++ f (append move-seq entry)))
    `(define ,locals (,f ,@args) ,blocks+++))
  (match p [`(program ,ds ...) `(program ,@(map per-defn ds))]))

;; ======================================================================
;; Pass 11: assign-homes — map vars to stack slots
;; ======================================================================
(define (assign-homes p)
  (define (per-defn d)
    (match-define `(define ,locals (,f ,args ...) ,blocks) d)
    (define var->loc
      (let ([l (set->list locals)])
        (foldl (lambda (v i h) (hash-set h v (* -8 i))) (hash) l (range 1 (add1 (length l))))))
    (define (home a)
      (match a
        [`(var ,x) `(deref (reg rbp) ,(hash-ref var->loc x 'unknown))]
        [`(imm ,i) a] [`(reg ,r) a] [`(byte-reg ,r) a] [`(deref ,_ ...) a]))
    (define (h blk)
      (match blk
        ['() '()]
        [`((retq) ,rest ...) (cons '(retq) (h rest))]
        [`((jmp ,l) ,rest ...) (cons `(jmp ,l) (h rest))]
        [`((jmp-if ,cc ,l) ,rest ...) (cons `(jmp-if ,cc ,l) (h rest))]
        [`((movq ,s ,d) ,rest ...) (cons `(movq ,(home s) ,(home d)) (h rest))]
        [`((movzbq ,s ,d) ,rest ...) (cons `(movzbq ,(home s) ,(home d)) (h rest))]
        [`((addq ,s ,d) ,rest ...) (cons `(addq ,(home s) ,(home d)) (h rest))]
        [`((negq ,o) ,rest ...) (cons `(negq ,(home o)) (h rest))]
        [`((xorq ,s ,d) ,rest ...) (cons `(xorq ,(home s) ,(home d)) (h rest))]
        [`((cmpq ,s ,d) ,rest ...) (cons `(cmpq ,(home s) ,(home d)) (h rest))]
        [`((set ,cc ,d) ,rest ...) (cons `(set ,cc ,(home d)) (h rest))]
        [`((pushq ,o) ,rest ...) (cons `(pushq ,(home o)) (h rest))]
        [`((popq ,o) ,rest ...) (cons `(popq ,(home o)) (h rest))]
        [`((callq ,fn ,i) ,rest ...) (cons `(callq ,fn ,i) (h rest))]
        [`((indirect-callq ,a) ,rest ...) (cons `(indirect-callq ,(home a)) (h rest))]
        [`((leaq (fun-ref ,f) ,d) ,rest ...) (cons `(leaq (fun-ref ,f) ,(home d)) (h rest))]))
    (define blocks+
      (foldl (lambda (k acc) (hash-set acc k (h (hash-ref blocks k)))) (hash) (hash-keys blocks)))
    `(define ,var->loc (,f ,@args) ,blocks+))
  (match p [`(program ,ds ...) `(program ,@(map per-defn ds))]))

;; ======================================================================
;; Pass 12: patch-instructions — fix illegal x86 forms
;; ======================================================================
(define (patch-instructions p)
  (define (deref? op) (match op [`(deref ,_ ...) #t] [_ #f]))
  (define (patch blk)
    (match blk
      ['() '()]
      ;; movq mem,mem → movq mem,rax; movq rax,mem
      [`((movq ,s ,d) ,rest ...) #:when (and (deref? s) (deref? d))
       `((movq ,s (reg rax)) (movq (reg rax) ,d) ,@(patch rest))]
      ;; addq mem,mem → movq src,rax; addq rax,dst
      [`((addq ,s ,d) ,rest ...) #:when (and (deref? s) (deref? d))
       `((movq ,s (reg rax)) (addq (reg rax) ,d) ,@(patch rest))]
      ;; cmpq mem,mem → movq src,rax; cmpq rax,dst
      [`((cmpq ,s ,d) ,rest ...) #:when (and (deref? s) (deref? d))
       `((movq ,s (reg rax)) (cmpq (reg rax) ,d) ,@(patch rest))]
      ;; cmpq *,imm → dst must be r/m in x86, not imm; move dst to rax
      [`((cmpq ,s ,d) ,rest ...) #:when (imm? d)
       `((movq ,d (reg rax)) (cmpq ,s (reg rax)) ,@(patch rest))]
      ;; xorq mem,mem
      [`((xorq ,s ,d) ,rest ...) #:when (and (deref? s) (deref? d))
       `((movq ,s (reg rax)) (xorq (reg rax) ,d) ,@(patch rest))]
      ;; movzbq to deref
      [`((movzbq ,s ,d) ,rest ...) #:when (deref? d)
       `((movzbq ,s (reg rax)) (movq (reg rax) ,d) ,@(patch rest))]
      ;; leaq to reg — OK
      [`((leaq ,src (reg ,r)) ,rest ...) `((leaq ,src (reg ,r)) ,@(patch rest))]
      ;; leaq to non-reg
      [`((leaq ,src ,dst) ,rest ...)
       `((leaq ,src (reg rax)) (movq (reg rax) ,dst) ,@(patch rest))]
      ;; default: keep instruction
      [`(,instr ,rest ...) (cons instr (patch rest))]))
  (define (per-defn d)
    (match-define `(define ,info (,f ,fs ...) ,blocks) d)
    (define blocks+
      (foldl (lambda (k a) (hash-set a k (patch (hash-ref blocks k)))) (hash) (hash-keys blocks)))
    `(define ,info (,f ,@fs) ,blocks+))
  (match p [`(program ,ds ...) `(program ,@(map per-defn ds))]))

;; ======================================================================
;; Pass 13: prelude-and-conclusion — add prologue/epilogue
;; ======================================================================
(define (prelude-and-conclusion p)
  (define (align16 n) (bitwise-and (+ n 15) (bitwise-not 15)))

  (define (rename-conclusion blocks name)
    (define (h-instr instr)
      (match instr
        [`(jmp ,blk) #:when (equal? blk (conclusion-block-name)) `(jmp ,name)]
        [i i]))
    (foldl (lambda (k acc) (hash-set acc k (map h-instr (hash-ref blocks k))))
           (hash) (hash-keys blocks)))

  (define (per-defn d)
    (match d
      [`(define ,locals (,f ,args ...) ,blocks)
       (define space-needed
         (if (empty? (hash-values locals)) 0
             (- (align16 (- (apply min (hash-values locals)))))))
       (define start-block (hash-ref blocks f))
       (define new-start
         `((pushq (reg rbp)) (movq (reg rsp) (reg rbp))
           (addq (imm ,space-needed) (reg rsp)) ,@start-block))
       (define concl-block
         (if (equal? f (entry-symbol))
             `((movq (reg rax) (reg rdi)) (callq print_int64 0)
               (movq (imm 0) (reg rax)) (movq (reg rbp) (reg rsp))
               (popq (reg rbp)) (retq))
             `((movq (reg rbp) (reg rsp)) (popq (reg rbp)) (retq))))
       (define my-concl (gensym 'conclusion))
       (define blocks+
         (rename-conclusion
          (hash-set (hash-remove (hash-set blocks f new-start)
                                (conclusion-block-name))
                   my-concl concl-block)
          my-concl))
       `(define ,locals (,f ,@args) ,blocks+)]))
  (match p [`(program ,ds ...) `(program ,@(map per-defn ds))]))

;; ======================================================================
;; Pass 14: dump-x86-64 — render GAS assembly
;; ======================================================================
(define (dump-x86-64 p)
  (define functions
    (set-add (list->set (match p [`(program ,_ (define ,_ (,fs ,_ ...) ,_) ...) fs])) 'main))
  (define (render-op op)
    (match op
      [`(imm ,i) (format "$~a" i)]
      [`(reg ,x) (format "%~a" (symbol->string x))]
      [`(byte-reg ,x) (format "%~a" (symbol->string x))]
      [`(deref (reg ,reg) ,i) (format "~a(%~a)" i (symbol->string reg))]))
  (define (render-instr instr)
    (match instr
      [`(movq ,s ,d)       (format "movq ~a, ~a" (render-op s) (render-op d))]
      [`(movzbq ,s ,d)     (format "movzbq ~a, ~a" (render-op s) (render-op d))]
      [`(addq ,s ,d)       (format "addq ~a, ~a" (render-op s) (render-op d))]
      [`(negq ,o)          (format "negq ~a" (render-op o))]
      [`(pushq ,o)         (format "pushq ~a" (render-op o))]
      [`(popq ,o)          (format "popq ~a" (render-op o))]
      [`(xorq ,s ,d)       (format "xorq ~a, ~a" (render-op s) (render-op d))]
      [`(cmpq ,s ,d)       (format "cmpq ~a, ~a" (render-op s) (render-op d))]
      [`(set ,cc ,d)       (format "set~a ~a" cc (render-op d))]
      [`(jmp ,l)           (format "jmp ~a" l)]
      [`(jmp-if ,cc ,l)    (format "j~a ~a" cc l)]
      [`(retq)             "retq"]
      [`(callq ,fn ,_)     (format "callq ~a" (rt-sym fn))]
      [`(leaq (fun-ref ,f) ,d)  (format "leaq ~a(%rip), ~a" (rt-sym f) (render-op d))]
      [`(indirect-callq ,a)     (format "callq *~a" (render-op a))]))
  (define (render-block block name)
    (define lbl (if (set-member? functions name) (format "~a:\n" (rt-sym name)) (format "~a:\n" name)))
    (apply string-append
           (cons lbl (map (lambda (i) (format "    ~a\n" (render-instr i))) block))))
  (define (per-defn d)
    (match-define `(define ,_ (,f ,fs ...) ,blocks) d)
    (foldl (lambda (k acc) (string-append acc (render-block (hash-ref blocks k) k)))
           "" (hash-keys blocks)))
  (match p
    [`(program ,ds ...)
     (string-append
      (format ".globl ~a\n" (rt-sym (entry-symbol)))
      (runtime-function-externs)
      (foldl (lambda (d acc) (string-append acc (per-defn d))) "" ds))]))
