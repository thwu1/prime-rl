
import sys
import os
import json
import subprocess
import importlib.util

sys.path.insert(0, "/app")


def load_ctr_drbg():
    spec = importlib.util.spec_from_file_location("ctr_drbg", "/app/impl_alpha/ctr_drbg.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CTR_DRBG


# ======================================================================
# Config 1: AES-256 use df, PersonalizationStringLen=0, AdditionalInputLen=0
# ======================================================================

class TestConfig1_UseDF_NoPers_NoAI:

    def test_count0_instantiate_state(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=True)
        entropy = bytes.fromhex(
            "36401940fa8b1fba91a1661f211d78a0b9389a74e5bccfece8d766af1a6d3b14"
        )
        nonce = bytes.fromhex("496f25b0f1301b4f501be30380a137eb")
        key, v = drbg.instantiate(entropy, nonce)
        assert key.hex() == "3363d9000e6db47c16d3fc65f2872c08a35f99b2d174afa537a66ec153052d98"
        assert v.hex() == "9ee8d2e9c618ccbb8e66b5eb5333dce1"

    def test_count0_gen1_state(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=True)
        entropy = bytes.fromhex(
            "36401940fa8b1fba91a1661f211d78a0b9389a74e5bccfece8d766af1a6d3b14"
        )
        nonce = bytes.fromhex("496f25b0f1301b4f501be30380a137eb")
        drbg.instantiate(entropy, nonce)
        _, key, v = drbg.generate(requested_bits=512)
        assert key.hex() == "b1dff09c816af6d4b2111fe63c4507cb196154f8c59957a94a2b641a7c16cc01"
        assert v.hex() == "69eec01b2dd4ff3aab5fac9467f54485"

    def test_count0_returned_bits(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=True)
        entropy = bytes.fromhex(
            "36401940fa8b1fba91a1661f211d78a0b9389a74e5bccfece8d766af1a6d3b14"
        )
        nonce = bytes.fromhex("496f25b0f1301b4f501be30380a137eb")
        drbg.instantiate(entropy, nonce)
        drbg.generate(requested_bits=512)
        bits, _, _ = drbg.generate(requested_bits=512)
        expected = (
            "5862eb38bd558dd978a696e6df164782ddd887e7e9a6c9f3"
            "f1fbafb78941b535a64912dfd224c6dc7454e5250b3d9716"
            "5e16260c2faf1cc7735cb75fb4f07e1d"
        )
        assert bits.hex() == expected

    def test_count1_returned_bits(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=True)
        entropy = bytes.fromhex(
            "13199090a47fbd1984eb5fa9589345154699ef73f00cd62b07c34167c0327e53"
        )
        nonce = bytes.fromhex("5f968f93b659d8a5750a95345a8ae20c")
        drbg.instantiate(entropy, nonce)
        drbg.generate(requested_bits=512)
        bits, _, _ = drbg.generate(requested_bits=512)
        expected = (
            "d16878c5b06d7b6ced8e8aeb3a48d95ec8dd655733eec6ef"
            "473a8078dfdea600c0cc02168b4d6d744ee828ba5031941f"
            "8e3d96586407af79eba60d14af47d53a"
        )
        assert bits.hex() == expected


# ======================================================================
# Config 2: AES-256 use df, PersonalizationStringLen=0, AdditionalInputLen=256
# ======================================================================

class TestConfig2_UseDF_NoPers_WithAI:

    def test_count0_instantiate_state(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=True)
        entropy = bytes.fromhex(
            "8148d65d86513ce7d38923ec2f26b9e7c677dcc8997e325b7372619e753ed944"
        )
        nonce = bytes.fromhex("41c71a24d17d974190982bb7515ce7f5")
        key, v = drbg.instantiate(entropy, nonce)
        assert key.hex() == "fe96784a3968b04aca2079e4bc1b7674e59d0bcb9d1168fb26cacd830ffde509"
        assert v.hex() == "24274380ee9aa72b730efae01987a16e"

    def test_count0_gen1_state(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=True)
        entropy = bytes.fromhex(
            "8148d65d86513ce7d38923ec2f26b9e7c677dcc8997e325b7372619e753ed944"
        )
        nonce = bytes.fromhex("41c71a24d17d974190982bb7515ce7f5")
        drbg.instantiate(entropy, nonce)
        ai1 = bytes.fromhex(
            "55b446046c2d14bdd0cdba4b71873fd4762650695a11507949462da8d964ab6a"
        )
        _, key, v = drbg.generate(additional_input=ai1, requested_bits=512)
        assert key.hex() == "ec013aa81ec90251e399774516481a22736bd89b5a5a6a7198da7cfceb741c59"
        assert v.hex() == "9e34cdda08a3c193231647953c73a8db"

    def test_count0_returned_bits(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=True)
        entropy = bytes.fromhex(
            "8148d65d86513ce7d38923ec2f26b9e7c677dcc8997e325b7372619e753ed944"
        )
        nonce = bytes.fromhex("41c71a24d17d974190982bb7515ce7f5")
        drbg.instantiate(entropy, nonce)
        ai1 = bytes.fromhex(
            "55b446046c2d14bdd0cdba4b71873fd4762650695a11507949462da8d964ab6a"
        )
        ai2 = bytes.fromhex(
            "91468f1a097d99ee339462ca916cb4a10f63d53850a4f17f598eac490299b02e"
        )
        drbg.generate(additional_input=ai1, requested_bits=512)
        bits, _, _ = drbg.generate(additional_input=ai2, requested_bits=512)
        expected = (
            "54603d1a506132bbfa05b153a04f22a1d516cc46323cef15"
            "111af221f030f38d6841d4670518b4914a4631af682e7421"
            "dffaac986a38e94d92bfa758e2eb101f"
        )
        assert bits.hex() == expected


# ======================================================================
# Config 3: AES-256 use df, PersonalizationStringLen=256, AdditionalInputLen=0
# ======================================================================

class TestConfig3_UseDF_WithPers_NoAI:

    def test_count0_instantiate_state(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=True)
        entropy = bytes.fromhex(
            "5416e77b5e1d872d4ff91973b1be66bc07f4a99e30db7d0006da006fcfb082db"
        )
        nonce = bytes.fromhex("7a811ce62b9fd34af186b2b3e50eaf5d")
        ps = bytes.fromhex(
            "71ee0c7699ac0e805632f2058de38bf872b8340f89998f7a8a2ad4ac045ae6ef"
        )
        key, v = drbg.instantiate(entropy, nonce, ps)
        assert key.hex() == "7c0d39f9032f89229e8ec342c31eb451305ff52ffd751b68b7b07f067134100f"
        assert v.hex() == "a7e1ccbc0558fb3f7471f695bc1e38cc"

    def test_count0_returned_bits(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=True)
        entropy = bytes.fromhex(
            "5416e77b5e1d872d4ff91973b1be66bc07f4a99e30db7d0006da006fcfb082db"
        )
        nonce = bytes.fromhex("7a811ce62b9fd34af186b2b3e50eaf5d")
        ps = bytes.fromhex(
            "71ee0c7699ac0e805632f2058de38bf872b8340f89998f7a8a2ad4ac045ae6ef"
        )
        drbg.instantiate(entropy, nonce, ps)
        drbg.generate(requested_bits=512)
        bits, _, _ = drbg.generate(requested_bits=512)
        expected = (
            "68f5859cf76f94c445d9fcd34fc17ac224c3d7d7c2fc38fa"
            "af3c24be6cd3cd93b7f9d8a6146f5ac83ac1d7b1b2b7e7ec"
            "bc1a2e38760ef86a577d402d85990d9b"
        )
        assert bits.hex() == expected


# ======================================================================
# Config 4: AES-256 use df, PersonalizationStringLen=256, AdditionalInputLen=256
# ======================================================================

class TestConfig4_UseDF_WithPers_WithAI:

    def test_count0_instantiate_state(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=True)
        entropy = bytes.fromhex(
            "87b56e964eba227154724bb9484b812d3e2c0c43b3d17f6098d9526e16e6d0ef"
        )
        nonce = bytes.fromhex("9bea6a7ff2358df142e6c23e2157fb83")
        ps = bytes.fromhex(
            "9860b432edd58d1ccbfeecbce99ffaee7d935a614860d4e965bd67041403096b"
        )
        key, v = drbg.instantiate(entropy, nonce, ps)
        assert key.hex() == "0313d4fd35635c8f46adf7747c46267b8f617f9dc61cc07b68e3a7b628d406b7"
        assert v.hex() == "db03f9651b7d7d5c78ac956c4da9006a"

    def test_count0_gen1_state(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=True)
        entropy = bytes.fromhex(
            "87b56e964eba227154724bb9484b812d3e2c0c43b3d17f6098d9526e16e6d0ef"
        )
        nonce = bytes.fromhex("9bea6a7ff2358df142e6c23e2157fb83")
        ps = bytes.fromhex(
            "9860b432edd58d1ccbfeecbce99ffaee7d935a614860d4e965bd67041403096b"
        )
        drbg.instantiate(entropy, nonce, ps)
        ai1 = bytes.fromhex(
            "99a5cc87924e8ea65a596f81fd17d63f5b4542fe6e8e1511b5d35c835dfadb0b"
        )
        _, key, v = drbg.generate(additional_input=ai1, requested_bits=512)
        assert key.hex() == "fae94976f1e438a714c73ed0a4ebe12999024b25295d13020dac58341cad12de"
        assert v.hex() == "fb04d990029d6c6c72a183ea8bd9e8dc"

    def test_count0_returned_bits(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=True)
        entropy = bytes.fromhex(
            "87b56e964eba227154724bb9484b812d3e2c0c43b3d17f6098d9526e16e6d0ef"
        )
        nonce = bytes.fromhex("9bea6a7ff2358df142e6c23e2157fb83")
        ps = bytes.fromhex(
            "9860b432edd58d1ccbfeecbce99ffaee7d935a614860d4e965bd67041403096b"
        )
        drbg.instantiate(entropy, nonce, ps)
        ai1 = bytes.fromhex(
            "99a5cc87924e8ea65a596f81fd17d63f5b4542fe6e8e1511b5d35c835dfadb0b"
        )
        ai2 = bytes.fromhex(
            "9a8dec54734a34582a2332f3452e82313524c3e0dfb485faeac6ca5fc0ff504d"
        )
        drbg.generate(additional_input=ai1, requested_bits=512)
        bits, _, _ = drbg.generate(additional_input=ai2, requested_bits=512)
        expected = (
            "dbc6a2330b19b5cddd8cd6392ec1fb508678c805e87d1aca"
            "07ac265007632503044a00610c79d98375afa7ab4cca1a90"
            "989cbfe7c674af5d823ced11c47e9af6"
        )
        assert bits.hex() == expected


# ======================================================================
# Config 5: AES-256 no df, PersonalizationStringLen=0, AdditionalInputLen=0
# ======================================================================

class TestConfig5_NoDF_NoPers_NoAI:

    def test_count0_instantiate_state(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=False)
        entropy = bytes.fromhex(
            "df5d73faa468649edda33b5cca79b0b05600419ccb7a879d"
            "dfec9db32ee494e5531b51de16a30f769262474c73bec010"
        )
        key, v = drbg.instantiate(entropy, b"")
        assert key.hex() == "8c52f901632d522774c08fad0eb2c33b98a701a1861aecf3d8a25860941709fd"
        assert v.hex() == "217b52142105250243c0b2c206b8f59e"

    def test_count0_gen1_state(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=False)
        entropy = bytes.fromhex(
            "df5d73faa468649edda33b5cca79b0b05600419ccb7a879d"
            "dfec9db32ee494e5531b51de16a30f769262474c73bec010"
        )
        drbg.instantiate(entropy, b"")
        _, key, v = drbg.generate(requested_bits=512)
        assert key.hex() == "72f4af5c93258eb3eeec8c0cacea6c1d1978a4fad44312725f1ac43b167f2d52"
        assert v.hex() == "e86f6d07dfb551cebad80e6bf6830ac4"

    def test_count0_returned_bits(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=False)
        entropy = bytes.fromhex(
            "df5d73faa468649edda33b5cca79b0b05600419ccb7a879d"
            "dfec9db32ee494e5531b51de16a30f769262474c73bec010"
        )
        drbg.instantiate(entropy, b"")
        drbg.generate(requested_bits=512)
        bits, _, _ = drbg.generate(requested_bits=512)
        expected = (
            "d1c07cd95af8a7f11012c84ce48bb8cb87189e99d40fccb1"
            "771c619bdf82ab2280b1dc2f2581f39164f7ac0c510494b3"
            "a43c41b7db17514c87b107ae793e01c5"
        )
        assert bits.hex() == expected

    def test_count1_returned_bits(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=False)
        entropy = bytes.fromhex(
            "3b6fb634d35bb386927374f991c1cbc9fafba3a43c432dc4"
            "11b7b2fa96cfcce8d305e135ff9bc460dbc7ba3990bf8060"
        )
        drbg.instantiate(entropy, b"")
        drbg.generate(requested_bits=512)
        bits, _, _ = drbg.generate(requested_bits=512)
        expected = (
            "083a836fe1cde053164555529409337dc4fec6844594fdf1"
            "5083ba9d1001eb945c3b96a1bcee3990e1e51f85c80e9f4e"
            "04de34e57b640f6cae8ed68e99624712"
        )
        assert bits.hex() == expected


# ======================================================================
# Config 6: AES-256 no df, PersonalizationStringLen=0, AdditionalInputLen=384
# ======================================================================

class TestConfig6_NoDF_NoPers_WithAI:

    def test_count0_instantiate_state(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=False)
        entropy = bytes.fromhex(
            "f45e9d040c1456f1c7f26e7f146469fbe3973007fe037239"
            "ad57623046e7ec52221b22eec208b22ac4cf4ca8d6253874"
        )
        key, v = drbg.instantiate(entropy, b"")
        assert key.hex() == "a75117ffcb5160486e91da8ed0af1a702d30703ab3631957aa19a7e3fc14714a"
        assert v.hex() == "507b2124f5ae985e156db926a3230dfa"

    def test_count0_gen1_state(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=False)
        entropy = bytes.fromhex(
            "f45e9d040c1456f1c7f26e7f146469fbe3973007fe037239"
            "ad57623046e7ec52221b22eec208b22ac4cf4ca8d6253874"
        )
        drbg.instantiate(entropy, b"")
        ai1 = bytes.fromhex(
            "28819bc79b92fc8790ebdc99812cdcea5c96e6feab32801e"
            "c1851b9f46e80eb6800028e61fbccb6ccbe42b06bf5a0864"
        )
        _, key, v = drbg.generate(additional_input=ai1, requested_bits=512)
        assert key.hex() == "d75e41010982abd243b4d75642b86ce07e13b3652a3725aad011b1097c32957a"
        assert v.hex() == "939fbb584e0103982d2e73e05779849f"

    def test_count0_returned_bits(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=False)
        entropy = bytes.fromhex(
            "f45e9d040c1456f1c7f26e7f146469fbe3973007fe037239"
            "ad57623046e7ec52221b22eec208b22ac4cf4ca8d6253874"
        )
        drbg.instantiate(entropy, b"")
        ai1 = bytes.fromhex(
            "28819bc79b92fc8790ebdc99812cdcea5c96e6feab32801e"
            "c1851b9f46e80eb6800028e61fbccb6ccbe42b06bf5a0864"
        )
        ai2 = bytes.fromhex(
            "418ca848027e1b3c84d66717e6f31bf89684d5db94cd2d57"
            "9233f716ac70ab66cc7b01a6f9ab8c7665fcc37dba4af1ad"
        )
        drbg.generate(additional_input=ai1, requested_bits=512)
        bits, _, _ = drbg.generate(additional_input=ai2, requested_bits=512)
        expected = (
            "4f11406bd303c104243441a8f828bf0293cb20ac39392061"
            "429c3f56c1f426239f8f0c687b69897a2c7c8c2b4fb520b6"
            "2741ffdd29f038b7c82a9d00a890a3ed"
        )
        assert bits.hex() == expected


# ======================================================================
# Config 7: AES-256 no df, PersonalizationStringLen=384, AdditionalInputLen=0
# ======================================================================

class TestConfig7_NoDF_WithPers_NoAI:

    def test_count0_instantiate_state(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=False)
        entropy = bytes.fromhex(
            "22a89ee0e37b54ea636863d9fed10821f1952a428488d528"
            "eceb9d2ec69d573ec6216216fb3e8f72a148a5ada9d620b1"
        )
        ps = bytes.fromhex(
            "953c10badcbcd45fb4e5475826477fc137ac96a49ad5005f"
            "b14bdaf6468ae7f46c5d0de22d304afc67989615adc2e983"
        )
        key, v = drbg.instantiate(entropy, b"", ps)
        assert key.hex() == "e49b04a1f882b60c7eee90701c5d046b089efcdb533dbe195aee820b3ae42dd2"
        assert v.hex() == "d81c6c3ee1a8effa1772c6367112fcbc"

    def test_count0_returned_bits(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=False)
        entropy = bytes.fromhex(
            "22a89ee0e37b54ea636863d9fed10821f1952a428488d528"
            "eceb9d2ec69d573ec6216216fb3e8f72a148a5ada9d620b1"
        )
        ps = bytes.fromhex(
            "953c10badcbcd45fb4e5475826477fc137ac96a49ad5005f"
            "b14bdaf6468ae7f46c5d0de22d304afc67989615adc2e983"
        )
        drbg.instantiate(entropy, b"", ps)
        drbg.generate(requested_bits=512)
        bits, _, _ = drbg.generate(requested_bits=512)
        expected = (
            "f7fab6a6fcf445f0a0434b2aa0c610bdef5489ecd9541463"
            "4623add18a9f888bca6be151312d1b9e8f83bd0acad6234d"
            "3bccc11b63a40d6fbff448f67db0b91f"
        )
        assert bits.hex() == expected

    def test_count1_returned_bits(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=False)
        entropy = bytes.fromhex(
            "a5ca32ff18305555d32e270f170529232c458779eaace221"
            "ac4958b4226df8189e42b0844fc765751a6291a60a35d8b4"
        )
        ps = bytes.fromhex(
            "f42a3a32dc92a3eeff658c349eb2e181564458c202aa922e"
            "c4364e3a93b2ebdfb58ef78fc7237b70d8a261bcf30bd1b6"
        )
        drbg.instantiate(entropy, b"", ps)
        drbg.generate(requested_bits=512)
        bits, _, _ = drbg.generate(requested_bits=512)
        expected = (
            "00851cac3204326d97b5f26cd0bc05feafc34f56b5b7def2"
            "640bf5a12da0090d85320f3132fe7212c86d65f3b938366e"
            "ae25cd9233c0f9941a70f99e795cde4c"
        )
        assert bits.hex() == expected


# ======================================================================
# Config 8: AES-256 no df, PersonalizationStringLen=384, AdditionalInputLen=384
# ======================================================================

class TestConfig8_NoDF_WithPers_WithAI:

    def test_count0_instantiate_state(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=False)
        entropy = bytes.fromhex(
            "0dd4d80062ecc0f359efbe7723020be9b88b550fe7408809"
            "4069e74428395856f63eed4f5b0e7d1e006f0eaff74f638c"
        )
        ps = bytes.fromhex(
            "d2aa2ccd4bc6537e51f6550ab6d6294547bef3e971a7f128"
            "e4436f957de9982c93ee22110b0e40ab33a7d3dfa22f599d"
        )
        key, v = drbg.instantiate(entropy, b"", ps)
        assert key.hex() == "8c717e36ee6fa534a17a5f8c511f51273192e6dbdb87124fa3644d02ef235d62"
        assert v.hex() == "17b0cc9467a617c1e26a28fe20660f9f"

    def test_count0_returned_bits(self):
        CTR_DRBG = load_ctr_drbg()
        drbg = CTR_DRBG(keylen=32, use_df=False)
        entropy = bytes.fromhex(
            "0dd4d80062ecc0f359efbe7723020be9b88b550fe7408809"
            "4069e74428395856f63eed4f5b0e7d1e006f0eaff74f638c"
        )
        ps = bytes.fromhex(
            "d2aa2ccd4bc6537e51f6550ab6d6294547bef3e971a7f128"
            "e4436f957de9982c93ee22110b0e40ab33a7d3dfa22f599d"
        )
        drbg.instantiate(entropy, b"", ps)
        ai1 = bytes.fromhex(
            "0b081bab6c74d86b4a010e2ded99d14e0c9838f7c3d69afd"
            "64f1b66377d95cdcb7f6ec5358e3516034c3339ced7e1638"
        )
        ai2 = bytes.fromhex(
            "ca818f938ae0c7f4f507e4cfec10e7baf51fe34b89a502f7"
            "54d2d2be7395120fe1fb013c67ac2500b3d17b735da09a6e"
        )
        drbg.generate(additional_input=ai1, requested_bits=512)
        bits, _, _ = drbg.generate(additional_input=ai2, requested_bits=512)
        expected = (
            "6808268b13e236f642c06deba2494496e7003c937ebf6f7c"
            "b7c92104ea090f18484aa075560d7844a06eb559948c93b2"
            "6ae40f2db98ecb53ad593eb4c78f82b1"
        )
        assert bits.hex() == expected


# ======================================================================
# Audit report structure and content
# ======================================================================

class TestAuditReport:

    def test_report_exists(self):
        assert os.path.exists("/app/audit_report.json"), "audit_report.json not found"

    def test_report_top_level_structure(self):
        with open("/app/audit_report.json") as f:
            report = json.load(f)
        assert "implementations" in report
        assert "cross_validation" in report
        assert "recommendation" in report
        assert isinstance(report["implementations"], list)
        assert len(report["implementations"]) == 2

    def test_alpha_full_compliance(self):
        with open("/app/audit_report.json") as f:
            report = json.load(f)
        alpha = None
        for impl in report["implementations"]:
            if impl["name"] == "impl_alpha":
                alpha = impl
                break
        assert alpha is not None, "impl_alpha not found in report"
        assert alpha["total_vectors"] == 24
        assert alpha["passed"] == 24
        assert alpha["failed"] == 0
        assert alpha["compliance_verdict"] == "pass"

    def test_beta_partial_failure(self):
        with open("/app/audit_report.json") as f:
            report = json.load(f)
        beta = None
        for impl in report["implementations"]:
            if impl["name"] == "impl_beta":
                beta = impl
                break
        assert beta is not None, "impl_beta not found in report"
        assert beta["total_vectors"] == 24
        assert beta["passed"] == 6, f"Expected 6 passed, got {beta['passed']}"
        assert beta["failed"] == 18, f"Expected 18 failed, got {beta['failed']}"
        assert beta["compliance_verdict"] == "fail"

    def test_beta_defects_identified(self):
        with open("/app/audit_report.json") as f:
            report = json.load(f)
        beta = next(i for i in report["implementations"] if i["name"] == "impl_beta")
        assert "defects" in beta
        assert len(beta["defects"]) >= 2, (
            f"Expected at least 2 defects, found {len(beta['defects'])}"
        )
        for defect in beta["defects"]:
            assert "id" in defect, "Defect missing 'id'"
            assert "affected_configs" in defect, "Defect missing 'affected_configs'"
            assert "root_cause" in defect, "Defect missing 'root_cause'"
            assert "severity" in defect, "Defect missing 'severity'"
            assert defect["severity"] in ("critical", "high", "medium", "low"), (
                f"Invalid severity: {defect['severity']}"
            )
            assert "sp800_90a_section" in defect, "Defect missing 'sp800_90a_section'"

    def test_cross_validation_section(self):
        with open("/app/audit_report.json") as f:
            report = json.load(f)
        cv = report["cross_validation"]
        assert "intermediate_checks" in cv
        assert "checks_passed" in cv
        assert cv["intermediate_checks"] >= 3, (
            f"Expected >= 3 intermediate checks, got {cv['intermediate_checks']}"
        )
        assert cv["checks_passed"] >= 3

    def test_recommendation_nonempty(self):
        with open("/app/audit_report.json") as f:
            report = json.load(f)
        assert isinstance(report["recommendation"], str)
        assert len(report["recommendation"]) > 20, "Recommendation too short"


# ======================================================================
# Tooling verification
# ======================================================================

class TestTooling:

    def test_harness_beta_exists(self):
        assert os.path.exists("/app/harness_beta.py"), "harness_beta.py not found"

    def test_cross_validate_exists_and_executable(self):
        assert os.path.exists("/app/cross_validate.sh"), "cross_validate.sh not found"
        assert os.access("/app/cross_validate.sh", os.X_OK), (
            "cross_validate.sh is not executable"
        )

    def test_cross_validate_runs_successfully(self):
        result = subprocess.run(
            ["/bin/bash", "/app/cross_validate.sh"],
            capture_output=True, text=True, timeout=60, cwd="/app"
        )
        assert result.returncode == 0, (
            f"cross_validate.sh failed with rc={result.returncode}: {result.stderr}"
        )
