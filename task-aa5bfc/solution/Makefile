SRCDIR = src/main/java/swift
BUILDDIR = build

.PHONY: all build run validate-json validate-xml clean

all: build run validate-json validate-xml

build:
	mkdir -p $(BUILDDIR)
	javac -d $(BUILDDIR) $(SRCDIR)/*.java

run: build
	mkdir -p output
	java -cp $(BUILDDIR) swift.Mt103ValidationEngine messages/batch.fin output/report.json output/pacs008.xml

validate-json: run
	jq '[.[] | {ref: .reference, valid: .valid, stp: .stp_compliant, errors: (.errors | length)}]' output/report.json > output/summary.json

validate-xml: run
	xmllint --noout --schema schema/pacs008_subset.xsd output/pacs008.xml

clean:
	rm -rf $(BUILDDIR) output
