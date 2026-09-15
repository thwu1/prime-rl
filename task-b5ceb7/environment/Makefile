CC = gcc
CFLAGS = -Wall -O2

.PHONY: all sim validate clean

all: validate

config.h: gpu_config.json
	@echo "// Auto-generated from gpu_config.json - do not edit" > config.h
	@echo "#define NUM_BANKS $$(jq -r '.num_banks' gpu_config.json)" >> config.h
	@echo "#define BANK_WIDTH $$(jq -r '.bank_width_bytes' gpu_config.json)" >> config.h
	@echo "#define WARP_SIZE $$(jq -r '.warp_size' gpu_config.json)" >> config.h

bankmap: bankmap.c config.h
	$(CC) $(CFLAGS) -include config.h -o bankmap bankmap.c

sim:
	python3 sim.py

validate: sim
	bash validate.sh

clean:
	rm -f bankmap config.h sim_output.json
