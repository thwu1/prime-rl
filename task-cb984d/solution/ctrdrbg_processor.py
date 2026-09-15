"""
ACVP CTR-DRBG Test Vector Processor

Implements NIST SP 800-90A CTR-DRBG with:
- AES-128 and AES-256 block cipher modes
- Derivation function (Block_Cipher_df) and non-df modes
- Prediction resistance and explicit reseed test procedures

Reads /app/prompt.json, processes all test vectors, writes /app/response.json.
"""


import json
import struct
from Crypto.Cipher import AES


class CTR_DRBG:
    """SP 800-90A CTR_DRBG implementation."""

    def __init__(self, mode, use_df):
        if mode == "AES-128":
            self.keylen = 16
        elif mode == "AES-192":
            self.keylen = 24
        elif mode == "AES-256":
            self.keylen = 32
        else:
            raise ValueError(f"Unsupported mode: {mode}")

        self.outlen = 16  # AES block size in bytes
        self.seedlen = self.keylen + self.outlen
        self.use_df = use_df
        self.key = b'\x00' * self.keylen
        self.V = b'\x00' * self.outlen

    def _encrypt(self, key, plaintext):
        """Single AES-ECB block encryption."""
        cipher = AES.new(key, AES.MODE_ECB)
        return cipher.encrypt(plaintext)

    def _increment(self, V):
        """Increment V as a big-endian integer modulo 2^(outlen*8)."""
        val = int.from_bytes(V, 'big')
        val = (val + 1) % (1 << (self.outlen * 8))
        return val.to_bytes(self.outlen, 'big')

    def _xor(self, a, b):
        """XOR two byte strings of equal length."""
        return bytes(x ^ y for x, y in zip(a, b))

    def _update(self, provided_data, key, V):
        """
        CTR_DRBG_Update per SP 800-90A Section 10.2.1.2.
        provided_data must be exactly seedlen bytes.
        """
        temp = b''
        while len(temp) < self.seedlen:
            V = self._increment(V)
            temp += self._encrypt(key, V)
        temp = temp[:self.seedlen]
        temp = self._xor(temp, provided_data)
        new_key = temp[:self.keylen]
        new_V = temp[self.keylen:]
        return new_key, new_V

    def _bcc(self, key, data):
        """
        BCC function per SP 800-90A Section 10.3.3.
        data length must be a multiple of outlen.
        """
        chaining_value = b'\x00' * self.outlen
        n = len(data) // self.outlen
        for i in range(n):
            block = data[i * self.outlen:(i + 1) * self.outlen]
            input_block = self._xor(chaining_value, block)
            chaining_value = self._encrypt(key, input_block)
        return chaining_value

    def _block_cipher_df(self, input_string, no_of_bits_to_return):
        """
        Block_Cipher_df per SP 800-90A Section 10.3.2.
        Derives seed material from arbitrary-length input using BCC.
        """
        L = len(input_string)
        N = no_of_bits_to_return // 8

        # Build S = L || N || input_string || 0x80 || padding to outlen boundary
        S = struct.pack('>I', L) + struct.pack('>I', N) + input_string + b'\x80'
        while len(S) % self.outlen != 0:
            S += b'\x00'

        # K = leftmost keylen bytes of 0x00 01 02 03 ... 1F
        K = bytes(range(self.keylen))

        # Compute temp = BCC(K, IV_0 || S) || BCC(K, IV_1 || S) || ...
        temp = b''
        i = 0
        while len(temp) < self.keylen + self.outlen:
            IV = struct.pack('>I', i) + b'\x00' * (self.outlen - 4)
            temp += self._bcc(K, IV + S)
            i += 1

        K = temp[:self.keylen]
        X = temp[self.keylen:self.keylen + self.outlen]

        # Generate output by repeatedly encrypting X with K
        temp = b''
        while len(temp) < N:
            X = self._encrypt(K, X)
            temp += X

        return temp[:N]

    def instantiate(self, entropy_input, nonce, personalization_string):
        """
        CTR_DRBG_Instantiate per SP 800-90A Sections 10.2.1.3.1 / 10.2.1.3.2.
        """
        if self.use_df:
            # Section 10.2.1.3.1: with derivation function
            seed_material = entropy_input + nonce + personalization_string
            seed = self._block_cipher_df(seed_material, self.seedlen * 8)
        else:
            # Section 10.2.1.3.2: without derivation function
            ps = personalization_string
            if len(ps) < self.seedlen:
                ps = ps + b'\x00' * (self.seedlen - len(ps))
            seed = self._xor(entropy_input, ps[:self.seedlen])

        self.key = b'\x00' * self.keylen
        self.V = b'\x00' * self.outlen
        self.key, self.V = self._update(seed, self.key, self.V)

    def reseed(self, entropy_input, additional_input):
        """
        CTR_DRBG_Reseed per SP 800-90A Sections 10.2.1.4.1 / 10.2.1.4.2.
        """
        if self.use_df:
            # Section 10.2.1.4.1
            seed_material = entropy_input + additional_input
            seed = self._block_cipher_df(seed_material, self.seedlen * 8)
        else:
            # Section 10.2.1.4.2
            ai = additional_input
            if len(ai) < self.seedlen:
                ai = ai + b'\x00' * (self.seedlen - len(ai))
            seed = self._xor(entropy_input, ai[:self.seedlen])

        self.key, self.V = self._update(seed, self.key, self.V)

    def generate(self, requested_bits, additional_input=None):
        """
        CTR_DRBG_Generate per SP 800-90A Sections 10.2.1.5.1 / 10.2.1.5.2.
        Returns the generated pseudorandom bytes.
        """
        if additional_input is not None and len(additional_input) > 0:
            if self.use_df:
                # Section 10.2.1.5.1 step 2.1
                additional_input_processed = self._block_cipher_df(
                    additional_input, self.seedlen * 8
                )
            else:
                # Section 10.2.1.5.2 step 2
                ai = additional_input
                if len(ai) < self.seedlen:
                    ai = ai + b'\x00' * (self.seedlen - len(ai))
                additional_input_processed = ai[:self.seedlen]
            # Pre-generate update
            self.key, self.V = self._update(
                additional_input_processed, self.key, self.V
            )
        else:
            additional_input_processed = b'\x00' * self.seedlen

        # Generate output blocks
        temp = b''
        num_bytes = requested_bits // 8
        while len(temp) < num_bytes:
            self.V = self._increment(self.V)
            temp += self._encrypt(self.key, self.V)

        returned_bits = temp[:num_bytes]

        # Post-generate update
        self.key, self.V = self._update(
            additional_input_processed, self.key, self.V
        )

        return returned_bits


def process_test_case(mode, use_df, pred_resistance, reseed_flag,
                      returned_bits_len, test_case):
    """Process a single ACVP CTR-DRBG test case and return hex returnedBits."""
    drbg = CTR_DRBG(mode, use_df)

    entropy = bytes.fromhex(test_case['entropyInput'])
    nonce_hex = test_case.get('nonce', '')
    nonce = bytes.fromhex(nonce_hex) if nonce_hex else b''
    perso_hex = test_case.get('persoString', '')
    perso = bytes.fromhex(perso_hex) if perso_hex else b''

    drbg.instantiate(entropy, nonce, perso)

    other_inputs = test_case['otherInput']

    if pred_resistance:
        # SP 800-90A Section 9.3.1: prediction resistance mode
        # Each generate call reseeds first, then clears additional_input.
        # Test procedure (Table 7): Instantiate → Generate(discard) → Generate(output)

        # First generate (discard output)
        oi = other_inputs[0]
        reseed_entropy = bytes.fromhex(oi['entropyInput'])
        reseed_addl_hex = oi.get('additionalInput', '')
        reseed_addl = bytes.fromhex(reseed_addl_hex) if reseed_addl_hex else b''
        drbg.reseed(reseed_entropy, reseed_addl)
        # After reseed with prediction resistance, additional_input = Null
        drbg.generate(returned_bits_len, None)

        # Second generate (return output)
        oi = other_inputs[1]
        reseed_entropy = bytes.fromhex(oi['entropyInput'])
        reseed_addl_hex = oi.get('additionalInput', '')
        reseed_addl = bytes.fromhex(reseed_addl_hex) if reseed_addl_hex else b''
        drbg.reseed(reseed_entropy, reseed_addl)
        result = drbg.generate(returned_bits_len, None)

    elif reseed_flag:
        # Test procedure: Instantiate → Reseed → Generate(discard) → Generate(output)

        # Explicit reseed
        oi = other_inputs[0]
        assert oi['intendedUse'] == 'reSeed'
        reseed_entropy = bytes.fromhex(oi['entropyInput'])
        reseed_addl_hex = oi.get('additionalInput', '')
        reseed_addl = bytes.fromhex(reseed_addl_hex) if reseed_addl_hex else b''
        drbg.reseed(reseed_entropy, reseed_addl)

        # First generate (discard output)
        oi = other_inputs[1]
        assert oi['intendedUse'] == 'generate'
        addl_hex = oi.get('additionalInput', '')
        addl = bytes.fromhex(addl_hex) if addl_hex else None
        if addl is not None and len(addl) == 0:
            addl = None
        drbg.generate(returned_bits_len, addl)

        # Second generate (return output)
        oi = other_inputs[2]
        assert oi['intendedUse'] == 'generate'
        addl_hex = oi.get('additionalInput', '')
        addl = bytes.fromhex(addl_hex) if addl_hex else None
        if addl is not None and len(addl) == 0:
            addl = None
        result = drbg.generate(returned_bits_len, addl)

    else:
        # No prediction resistance, no reseed
        # Test procedure: Instantiate → Generate(discard) → Generate(output)

        # First generate (discard)
        oi = other_inputs[0]
        addl_hex = oi.get('additionalInput', '')
        addl = bytes.fromhex(addl_hex) if addl_hex else None
        if addl is not None and len(addl) == 0:
            addl = None
        drbg.generate(returned_bits_len, addl)

        # Second generate (return output)
        oi = other_inputs[1]
        addl_hex = oi.get('additionalInput', '')
        addl = bytes.fromhex(addl_hex) if addl_hex else None
        if addl is not None and len(addl) == 0:
            addl = None
        result = drbg.generate(returned_bits_len, addl)

    return result.hex().upper()


def main():
    with open('/app/prompt.json') as f:
        prompt = json.load(f)

    response = {
        'vsId': prompt['vsId'],
        'algorithm': prompt['algorithm'],
        'revision': prompt['revision'],
        'testGroups': []
    }

    for tg in prompt['testGroups']:
        mode = tg['mode']
        use_df = tg['derFunc']
        pred_resistance = tg['predResistance']
        reseed_flag = tg['reSeed']
        returned_bits_len = tg['returnedBitsLen']

        resp_tg = {'tgId': tg['tgId'], 'tests': []}

        for tc in tg['tests']:
            returned_bits_hex = process_test_case(
                mode, use_df, pred_resistance, reseed_flag,
                returned_bits_len, tc
            )
            resp_tg['tests'].append({
                'tcId': tc['tcId'],
                'returnedBits': returned_bits_hex
            })

        response['testGroups'].append(resp_tg)

    with open('/app/response.json', 'w') as f:
        json.dump(response, f, indent=2)

    print(f"Processed {sum(len(tg['tests']) for tg in response['testGroups'])} test cases")
    print("Response written to /app/response.json")


if __name__ == '__main__':
    main()
