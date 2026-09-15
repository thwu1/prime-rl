SRCDIR = /app/src
BUILDDIR = /app/build
JARFILE = /app/checker.jar


.PHONY: compile jar clean

compile:
	mkdir -p $(BUILDDIR)
	javac -d $(BUILDDIR) $(SRCDIR)/Types.java $(SRCDIR)/Main.java

jar:
	jar cfm $(JARFILE) /app/MANIFEST.MF -C $(SRCDIR) .

clean:
	rm -rf $(BUILDDIR) $(JARFILE)
