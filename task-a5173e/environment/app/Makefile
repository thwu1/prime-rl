IVERILOG = iverilog
VVP = vvp

all: test

decrypt_test: aes128_encrypt.v aes128_decrypt.v tb_aes128_decrypt.v
	$(IVERILOG) -o decrypt_test aes128_encrypt.v aes128_decrypt.v tb_aes128_decrypt.v

test: decrypt_test
	$(VVP) decrypt_test

clean:
	rm -f decrypt_test

.PHONY: all test clean
