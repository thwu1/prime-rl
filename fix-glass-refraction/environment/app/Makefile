SCENE = /app/scene.yaml
OUTPUT = /app/output.ppm

.PHONY: all render verify clean

all: render verify

render: $(SCENE)
	python3 /app/render_scene.py

verify:
	@test -f $(OUTPUT) || { echo "FAIL: $(OUTPUT) not found"; exit 1; }
	@echo "Checking image metadata..."
	@pamfile $(OUTPUT)
	@pamfile $(OUTPUT) | grep -q "100 by 75" || { echo "FAIL: expected 100 by 75"; exit 1; }
	@echo "Checking color histogram..."
	@NCOLORS=$$(ppmhist $(OUTPUT) | grep -cE '^\s+[0-9]'); echo "Distinct colors: $$NCOLORS"; [ "$$NCOLORS" -ge 20 ] || { echo "FAIL: need >= 20 distinct colors"; exit 1; }
	@echo "PASS"

clean:
	rm -f $(OUTPUT)
