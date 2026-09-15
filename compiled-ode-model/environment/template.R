# Extended Robertson Reaction System — deSolve solver template
#
# The C source at /app/robertson_ext.c provides initmod, initforc, and
# derivs. After compiling with R CMD SHLIB, load the shared library
# with dyn.load() and pass function names as strings to ode().
#
# See the deSolve package vignette "compiledCode" for the full DLL
# interface specification, and ?forcings for forcing function setup.

library(deSolve)
