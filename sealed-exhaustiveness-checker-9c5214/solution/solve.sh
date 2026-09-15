#!/bin/bash

# Fix Makefile bug 1: add missing ExhaustivenessChecker.java to compile target
sed -i 's|$(SRCDIR)/Types.java $(SRCDIR)/Main.java|$(SRCDIR)/*.java|' /app/Makefile

# Fix Makefile bug 2: jar should package compiled classes (BUILDDIR) not sources (SRCDIR)
sed -i 's|-C $(SRCDIR) .|-C $(BUILDDIR) .|' /app/Makefile

# Fix Makefile bug 3: jar target must depend on compile
sed -i 's/^jar:$/jar: compile/' /app/Makefile

# Fix MANIFEST.MF: Main-Class should be Main, not ExhaustivenessChecker
sed -i 's/Main-Class: ExhaustivenessChecker/Main-Class: Main/' /app/MANIFEST.MF

# Fix ExhaustivenessChecker.java logic bugs
cp /solution/ExhaustivenessChecker.java /app/src/ExhaustivenessChecker.java

# Build the project
make -C /app clean
make -C /app jar
