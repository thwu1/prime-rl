#!/bin/bash

# Copy fixed source files over the buggy ones
cp /solution/UnaryTestEvaluator.java /app/src/feel/UnaryTestEvaluator.java
cp /solution/HitPolicyEngine.java /app/src/feel/HitPolicyEngine.java
cp /solution/DecisionTableEngine.java /app/src/feel/DecisionTableEngine.java

# Recompile
cd /app
/app/build.sh
