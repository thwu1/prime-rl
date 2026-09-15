SRCDIR = src
BUILDDIR = build

SOURCES = $(shell find $(SRCDIR) -name "*.java")

.PHONY: compile run run-por clean

compile:
	mkdir -p $(BUILDDIR)
	@for src in $(SOURCES); do \
		javac -d $(BUILDDIR) $$src || exit 1; \
	done

run:
	java -cp $(BUILDDIR) modelchecker.Main

run-por:
	java -cp $(BUILDDIR) modelchecker.Main --por

clean:
	rm -rf $(BUILDDIR)
