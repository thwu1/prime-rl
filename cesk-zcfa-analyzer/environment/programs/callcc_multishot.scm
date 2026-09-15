(let ((saved #f))
  (let ((n (call/cc (lambda (k)
    (let ((_ (set! saved k)))
      5)))))
    (let ((small (< n 2)))
      (if small
        n
        (let ((n1 (- n 1)))
          (saved n1))))))
