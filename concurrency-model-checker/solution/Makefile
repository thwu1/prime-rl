SRCDIR = src
BUILDDIR = build

SOURCES = $(shell find $(SRCDIR) -name "*.java")

.PHONY: compile run run-por clean

compile:
	mkdir -p $(BUILDDIR)
	javac -d $(BUILDDIR) $(SOURCES)

run:
	java -cp $(BUILDDIR) Main

run-por:
	java -cp $(BUILDDIR) Main --por

clean:
	rm -rf $(BUILDDIR)
