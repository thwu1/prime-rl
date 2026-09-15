/* Generate secure ECC parameters: composite modulus with non-smooth       */
/* curve orders that resist Pohlig-Hellman decomposition.                  */
default(parisizemax, 268435456);
{
  a = 1; b = 1;
  found = 0;
  while(!found,
    p = randomprime([2^79, 2^80]);
    q = randomprime([2^79, 2^80]);
    if(p != q,
      Ep = ellinit([a, b], p);
      Eq = ellinit([a, b], q);
      op = ellcard(Ep);
      oq = ellcard(Eq);
      fp = factor(op);
      fq = factor(oq);
      lpfp = fp[matsize(fp)[1], 1];
      lpfq = fq[matsize(fq)[1], 1];
      if(lpfp >= 2^64 && lpfq >= 2^64,
        n = p * q;
        for(xv = 1, 100000,
          y2p = Mod(xv^3 + a*xv + b, p);
          y2q = Mod(xv^3 + a*xv + b, q);
          if(issquare(y2p, &yp) && issquare(y2q, &yq),
            yv = lift(chinese(Mod(lift(yp), p), Mod(lift(yq), q)));
            print(p);
            print(q);
            print(a);
            print(b);
            print(xv);
            print(yv);
            found = 1;
            break
          )
        )
      )
    )
  )
}
quit
