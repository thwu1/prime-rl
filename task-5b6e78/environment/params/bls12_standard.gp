default(linewrap, 0);
u = -0xd201000000010000;
p = (u-1)^2 * (u^4 - u^2 + 1) / 3 + u;
r = u^4 - u^2 + 1;
print("PARAM_U=", u);
print("PARAM_P=", p);
print("PARAM_R=", r);
\q
