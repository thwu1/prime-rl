(let ((f (lambda (x) (+ x 1))))
  (let ((g (lambda (y) (* y 2))))
    (let ((_ (set! f g)))
      (f 5))))
