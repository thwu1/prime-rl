RUST_LIB = rust-sortedset/target/release/librust_sortedset.a
CFLAGS = -Wall -Wextra -Iinclude -pthread
LDFLAGS = -lpthread -ldl -lm

all: sortedset_test

sortedset_test: src/main.c $(RUST_LIB)
	gcc $(CFLAGS) -o $@ $< $(RUST_LIB) $(LDFLAGS)

$(RUST_LIB):
	cd rust-sortedset && cargo build --release

clean:
	rm -f sortedset_test
	cd rust-sortedset && cargo clean

.PHONY: all clean
