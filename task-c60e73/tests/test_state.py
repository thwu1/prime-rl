"""
Ed25519 implementation verification tests.
Tests key derivation, signing, verification, tamper rejection, and malleability rejection
against RFC 8032 Section 7.1 vectors and SUPERCOP sign.input vectors.
"""


import subprocess
import os
import pytest

TOOL = "/app/ed25519_tool"

# Ed25519 group order L = 2^252 + 27742317777372353535851937790883648493
L = 2**252 + 27742317777372353535851937790883648493

# ── RFC 8032 Section 7.1 Test Vectors ──────────────────────────────────────

RFC_VECTORS = [
    {   # TEST 1 - empty message
        "secret": "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "pubkey": "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "msg": "",
        "sig": "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
               "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    },
    {   # TEST 2 - 1 byte
        "secret": "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "pubkey": "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "msg": "72",
        "sig": "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
               "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    },
    {   # TEST 3 - 2 bytes
        "secret": "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
        "pubkey": "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
        "msg": "af82",
        "sig": "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
               "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a",
    },
    {   # TEST 1024 - 1023 bytes
        "secret": "f5e5767cf153319517630f226876b86c8160cc583bc013744c6bf255f5cc0ee5",
        "pubkey": "278117fc144c72340f67d0f2316e8386ceffbf2b2428c9c51fef7c597f1d426e",
        "msg": "08b8b2b733424243760fe426a4b54908"
               "632110a66c2f6591eabd3345e3e4eb98"
               "fa6e264bf09efe12ee50f8f54e9f77b1"
               "e355f6c50544e23fb1433ddf73be84d8"
               "79de7c0046dc4996d9e773f4bc9efe57"
               "38829adb26c81b37c93a1b270b20329d"
               "658675fc6ea534e0810a4432826bf58c"
               "941efb65d57a338bbd2e26640f89ffbc"
               "1a858efcb8550ee3a5e1998bd177e93a"
               "7363c344fe6b199ee5d02e82d522c4fe"
               "ba15452f80288a821a579116ec6dad2b"
               "3b310da903401aa62100ab5d1a36553e"
               "06203b33890cc9b832f79ef80560ccb9"
               "a39ce767967ed628c6ad573cb116dbef"
               "efd75499da96bd68a8a97b928a8bbc10"
               "3b6621fcde2beca1231d206be6cd9ec7"
               "aff6f6c94fcd7204ed3455c68c83f4a4"
               "1da4af2b74ef5c53f1d8ac70bdcb7ed1"
               "85ce81bd84359d44254d95629e9855a9"
               "4a7c1958d1f8ada5d0532ed8a5aa3fb2"
               "d17ba70eb6248e594e1a2297acbbb39d"
               "502f1a8c6eb6f1ce22b3de1a1f40cc24"
               "554119a831a9aad6079cad88425de6bd"
               "e1a9187ebb6092cf67bf2b13fd65f270"
               "88d78b7e883c8759d2c4f5c65adb7553"
               "878ad575f9fad878e80a0c9ba63bcbcc"
               "2732e69485bbc9c90bfbd62481d9089b"
               "eccf80cfe2df16a2cf65bd92dd597b07"
               "07e0917af48bbb75fed413d238f5555a"
               "7a569d80c3414a8d0859dc65a46128ba"
               "b27af87a71314f318c782b23ebfe808b"
               "82b0ce26401d2e22f04d83d1255dc51a"
               "ddd3b75a2b1ae0784504df543af8969b"
               "e3ea7082ff7fc9888c144da2af58429e"
               "c96031dbcad3dad9af0dcbaaaf268cb8"
               "fcffead94f3c7ca495e056a9b47acdb7"
               "51fb73e666c6c655ade8297297d07ad1"
               "ba5e43f1bca32301651339e22904cc8c"
               "42f58c30c04aafdb038dda0847dd988d"
               "cda6f3bfd15c4b4c4525004aa06eeff8"
               "ca61783aacec57fb3d1f92b0fe2fd1a8"
               "5f6724517b65e614ad6808d6f6ee34df"
               "f7310fdc82aebfd904b01e1dc54b2927"
               "094b2db68d6f903b68401adebf5a7e08"
               "d78ff4ef5d63653a65040cf9bfd4aca7"
               "984a74d37145986780fc0b16ac451649"
               "de6188a7dbdf191f64b5fc5e2ab47b57"
               "f7f7276cd419c17a3ca8e1b939ae49e4"
               "88acba6b965610b5480109c8b17b80e1"
               "b7b750dfc7598d5d5011fd2dcc5600a3"
               "2ef5b52a1ecc820e308aa342721aac09"
               "43bf6686b64b2579376504ccc493d97e"
               "6aed3fb0f9cd71a43dd497f01f17c0e2"
               "cb3797aa2a2f256656168e6c496afc5f"
               "b93246f6b1116398a346f1a641f3b041"
               "e989f7914f90cc2c7fff357876e506b5"
               "0d334ba77c225bc307ba537152f3f161"
               "0e4eafe595f6d9d90d11faa933a15ef1"
               "369546868a7f3a45a96768d40fd9d034"
               "12c091c6315cf4fde7cb68606937380d"
               "b2eaaa707b4c4185c32eddcdd306705e"
               "4dc1ffc872eeee475a64dfac86aba41c"
               "0618983f8741c5ef68d3a101e8a3b8ca"
               "c60c905c15fc910840b94c00a0b9d0",
        "sig": "0aab4c900501b3e24d7cdf4663326a3a87df5e4843b2cbdb67cbf6e460fec350"
               "aa5371b1508f9f4528ecea23c436d94b5e8fcd4f681e30a6ac00a9704a188a03",
    },
    {   # TEST SHA(abc) - 64 bytes
        "secret": "833fe62409237b9d62ec77587520911e9a759cec1d19755b7da901b96dca3d42",
        "pubkey": "ec172b93ad5e563bf4932c70e1245034c35467ef2efd4d64ebf819683467e2bf",
        "msg": "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
               "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f",
        "sig": "dc2a4459e7369633a52b1bf277839a00201009a3efbf3ecb69bea2186c26b589"
               "09351fc9ac90b3ecfdfbc7c66431e0303dca179c138ac17ad9bef1177331a704",
    },
]

# ── SUPERCOP sign.input vectors (first 20) ─────────────────────────────────
# Format per line: secret+pubkey : pubkey : msg : sig+msg
SUPERCOP_LINES = [
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a:d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a::e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b:",
    "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c:3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c:72:92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c0072:",
    "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025:fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025:af82:6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40aaf82:",
    "0d4a05b07352a5436e180356da0ae6efa0345ff7fb1572575772e8005ed978e9e61a185bcef2613a6c7cb79763ce945d3b245d76114dd440bcf5f2dc1aa57057:e61a185bcef2613a6c7cb79763ce945d3b245d76114dd440bcf5f2dc1aa57057:cbc77b:d9868d52c2bebce5f3fa5a79891970f309cb6591e3e1702a70276fa97c24b3a8e58606c38c9758529da50ee31b8219cba45271c689afa60b0ea26c99db19b00ccbc77b:",
    "6df9340c138cc188b5fe4464ebaa3f7fc206a2d55c3434707e74c9fc04e20ebbc0dac102c4533186e25dc43128472353eaabdb878b152aeb8e001f92d90233a7:c0dac102c4533186e25dc43128472353eaabdb878b152aeb8e001f92d90233a7:5f4c8989:124f6fc6b0d100842769e71bd530664d888df8507df6c56dedfdb509aeb93416e26b918d38aa06305df3095697c18b2aa832eaa52edc0ae49fbae5a85e150c075f4c8989:",
    "b780381a65edf8b78f6945e8dbec7941ac049fd4c61040cf0c324357975a293ce253af0766804b869bb1595be9765b534886bbaab8305bf50dbc7f899bfb5f01:e253af0766804b869bb1595be9765b534886bbaab8305bf50dbc7f899bfb5f01:18b6bec097:b2fc46ad47af464478c199e1f8be169f1be6327c7f9a0a6689371ca94caf04064a01b22aff1520abd58951341603faed768cf78ce97ae7b038abfe456aa17c0918b6bec097:",
    "78ae9effe6f245e924a7be63041146ebc670dbd3060cba67fbc6216febc44546fbcfbfa40505d7f2be444a33d185cc54e16d615260e1640b2b5087b83ee3643d:fbcfbfa40505d7f2be444a33d185cc54e16d615260e1640b2b5087b83ee3643d:89010d855972:6ed629fc1d9ce9e1468755ff636d5a3f40a5d9c91afd93b79d241830f7e5fa29854b8f20cc6eecbb248dbd8d16d14e99752194e4904d09c74d639518839d230089010d855972:",
    "691865bfc82a1e4b574eecde4c7519093faf0cf867380234e3664645c61c5f7998a5e3a36e67aaba89888bf093de1ad963e774013b3902bfab356d8b90178a63:98a5e3a36e67aaba89888bf093de1ad963e774013b3902bfab356d8b90178a63:b4a8f381e70e7a:6e0af2fe55ae377a6b7a7278edfb419bd321e06d0df5e27037db8812e7e3529810fa5552f6c0020985ca17a0e02e036d7b222a24f99b77b75fdd16cb05568107b4a8f381e70e7a:",
    "3b26516fb3dc88eb181b9ed73f0bcd52bcd6b4c788e4bcaf46057fd078bee073f81fb54a825fced95eb033afcd64314075abfb0abd20a970892503436f34b863:f81fb54a825fced95eb033afcd64314075abfb0abd20a970892503436f34b863:4284abc51bb67235:d6addec5afb0528ac17bb178d3e7f2887f9adbb1ad16e110545ef3bc57f9de2314a5c8388f723b8907be0f3ac90c6259bbe885ecc17645df3db7d488f805fa084284abc51bb67235:",
    "edc6f5fbdd1cee4d101c063530a30490b221be68c036f5b07d0f953b745df192c1a49c66e617f9ef5ec66bc4c6564ca33de2a5fb5e1464062e6d6c6219155efd:c1a49c66e617f9ef5ec66bc4c6564ca33de2a5fb5e1464062e6d6c6219155efd:672bf8965d04bc5146:2c76a04af2391c147082e33faacdbe56642a1e134bd388620b852b901a6bc16ff6c9cc9404c41dea12ed281da067a1513866f9d964f8bdd24953856c50042901672bf8965d04bc5146:",
    "4e7d21fb3b1897571a445833be0f9fd41cd62be3aa04040f8934e1fcbdcacd4531b2524b8348f7ab1dfafa675cc538e9a84e3fe5819e27c12ad8bbc1a36e4dff:31b2524b8348f7ab1dfafa675cc538e9a84e3fe5819e27c12ad8bbc1a36e4dff:33d7a786aded8c1bf691:28e4598c415ae9de01f03f9f3fab4e919e8bf537dd2b0cdf6e79b9e6559c9409d9151a4c40f083193937627c369488259e99da5a9f0a87497fa6696a5dd6ce0833d7a786aded8c1bf691:",
    "a980f892db13c99a3e8971e965b2ff3d41eafd54093bc9f34d1fd22d84115bb644b57ee30cdb55829d0a5d4f046baef078f1e97a7f21b62d75f8e96ea139c35f:44b57ee30cdb55829d0a5d4f046baef078f1e97a7f21b62d75f8e96ea139c35f:3486f68848a65a0eb5507d:77d389e599630d934076329583cd4105a649a9292abc44cd28c40000c8e2f5ac7660a81c85b72af8452d7d25c070861dae91601c7803d656531650dd4e5c41003486f68848a65a0eb5507d:",
    "5b5a619f8ce1c66d7ce26e5a2ae7b0c04febcd346d286c929e19d0d5973bfef96fe83693d011d111131c4f3fbaaa40a9d3d76b30012ff73bb0e39ec27ab18257:6fe83693d011d111131c4f3fbaaa40a9d3d76b30012ff73bb0e39ec27ab18257:5a8d9d0a22357e6655f9c785:0f9ad9793033a2fa06614b277d37381e6d94f65ac2a5a94558d09ed6ce922258c1a567952e863ac94297aec3c0d0c8ddf71084e504860bb6ba27449b55adc40e5a8d9d0a22357e6655f9c785:",
    "940c89fe40a81dafbdb2416d14ae469119869744410c3303bfaa0241dac57800a2eb8c0501e30bae0cf842d2bde8dec7386f6b7fc3981b8c57c9792bb94cf2dd:a2eb8c0501e30bae0cf842d2bde8dec7386f6b7fc3981b8c57c9792bb94cf2dd:b87d3813e03f58cf19fd0b6395:d8bb64aad8c9955a115a793addd24f7f2b077648714f49c4694ec995b330d09d640df310f447fd7b6cb5c14f9fe9f490bcf8cfadbfd2169c8ac20d3b8af49a0cb87d3813e03f58cf19fd0b6395:",
    "9acad959d216212d789a119252ebfe0c96512a23c73bd9f3b202292d6916a738cf3af898467a5b7a52d33d53bc037e2642a8da996903fc252217e9c033e2f291:cf3af898467a5b7a52d33d53bc037e2642a8da996903fc252217e9c033e2f291:55c7fa434f5ed8cdec2b7aeac173:6ee3fe81e23c60eb2312b2006b3b25e6838e02106623f844c44edb8dafd66ab0671087fd195df5b8f58a1d6e52af42908053d55c7321010092748795ef94cf0655c7fa434f5ed8cdec2b7aeac173:",
    "d5aeee41eeb0e9d1bf8337f939587ebe296161e6bf5209f591ec939e1440c300fd2a565723163e29f53c9de3d5e8fbe36a7ab66e1439ec4eae9c0a604af291a5:fd2a565723163e29f53c9de3d5e8fbe36a7ab66e1439ec4eae9c0a604af291a5:0a688e79be24f866286d4646b5d81c:f68d04847e5b249737899c014d31c805c5007a62c0a10d50bb1538c5f35503951fbc1e08682f2cc0c92efe8f4985dec61dcbd54d4b94a22547d24451271c8b000a688e79be24f866286d4646b5d81c:",
    "0a47d10452ae2febec518a1c7c362890c3fc1a49d34b03b6467d35c904a8362d34e5a8508c4743746962c066e4badea2201b8ab484de5c4f94476ccd2143955b:34e5a8508c4743746962c066e4badea2201b8ab484de5c4f94476ccd2143955b:c942fa7ac6b23ab7ff612fdc8e68ef39:2a3d27dc40d0a8127949a3b7f908b3688f63b7f14f651aacd715940bdbe27a0809aac142f47ab0e1e44fa490ba87ce5392f33a891539caf1ef4c367cae54500cc942fa7ac6b23ab7ff612fdc8e68ef39:",
    "f8148f7506b775ef46fdc8e8c756516812d47d6cfbfa318c27c9a22641e56f170445e456dacc7d5b0bbed23c8200cdb74bdcb03e4c7b73f0a2b9b46eac5d4372:0445e456dacc7d5b0bbed23c8200cdb74bdcb03e4c7b73f0a2b9b46eac5d4372:7368724a5b0efb57d28d97622dbde725af:3653ccb21219202b8436fb41a32ba2618c4a133431e6e63463ceb3b6106c4d56e1d2ba165ba76eaad3dc39bffb130f1de3d8e6427db5b71938db4e272bc3e20b7368724a5b0efb57d28d97622dbde725af:",
    "77f88691c4eff23ebb7364947092951a5ff3f10785b417e918823a552dab7c7574d29127f199d86a8676aec33b4ce3f225ccb191f52c191ccd1e8cca65213a6b:74d29127f199d86a8676aec33b4ce3f225ccb191f52c191ccd1e8cca65213a6b:bd8e05033f3a8bcdcbf4beceb70901c82e31:fbe929d743a03c17910575492f3092ee2a2bf14a60a3fcacec74a58c7334510fc262db582791322d6c8c41f1700adb80027ecabc14270b703444ae3ee7623e0abd8e05033f3a8bcdcbf4beceb70901c82e31:",
    "ab6f7aee6a0837b334ba5eb1b2ad7fcecfab7e323cab187fe2e0a95d80eff1325b96dca497875bf9664c5e75facf3f9bc54bae913d66ca15ee85f1491ca24d2c:5b96dca497875bf9664c5e75facf3f9bc54bae913d66ca15ee85f1491ca24d2c:8171456f8b907189b1d779e26bc5afbb08c67a:73bca64e9dd0db88138eedfafcea8f5436cfb74bfb0e7733cf349baa0c49775c56d5934e1d38e36f39b7c5beb0a836510c45126f8ec4b6810519905b0ca07c098171456f8b907189b1d779e26bc5afbb08c67a:",
]


def parse_supercop_line(line):
    """Parse a SUPERCOP sign.input line into (secret, pubkey, msg, sig)."""
    fields = line.strip().rstrip(":").split(":")
    secret = fields[0][:64]   # first 32 bytes of field 0
    pubkey = fields[1]
    msg = fields[2]
    sig = fields[3][:128]     # first 64 bytes of field 3
    return secret, pubkey, msg, sig


def run_tool(args, timeout=60):
    """Run ed25519_tool with the given arguments and return stdout."""
    result = subprocess.run(
        [TOOL] + args,
        capture_output=True, text=True, timeout=timeout
    )
    return result.stdout.strip(), result.returncode


# ── Build ──────────────────────────────────────────────────────────────────

class TestBuild:
    def test_make_succeeds(self):
        result = subprocess.run(
            ["make", "-C", "/app", "clean"],
            capture_output=True, text=True, timeout=30
        )
        result = subprocess.run(
            ["make", "-C", "/app"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, f"make failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"

    def test_tool_exists(self):
        assert os.path.isfile(TOOL), f"{TOOL} not found after make"


# ── Key Derivation ─────────────────────────────────────────────────────────

class TestKeyDerivation:
    @pytest.mark.parametrize("vec_idx", range(len(RFC_VECTORS)))
    def test_rfc_keygen(self, vec_idx):
        v = RFC_VECTORS[vec_idx]
        out, rc = run_tool(["keygen", v["secret"]])
        assert rc == 0, f"keygen returned non-zero exit code"
        assert out == v["pubkey"], (
            f"RFC vector {vec_idx}: expected pubkey {v['pubkey']}, got {out}"
        )


# ── Signing ────────────────────────────────────────────────────────────────

class TestSigning:
    @pytest.mark.parametrize("vec_idx", range(len(RFC_VECTORS)))
    def test_rfc_sign(self, vec_idx):
        v = RFC_VECTORS[vec_idx]
        out, rc = run_tool(["sign", v["secret"], v["msg"]])
        assert rc == 0, f"sign returned non-zero exit code"
        assert out == v["sig"], (
            f"RFC vector {vec_idx}: signature mismatch.\n"
            f"Expected: {v['sig']}\nGot:      {out}"
        )

    def test_sign_deterministic(self):
        """Same inputs must produce the same signature."""
        v = RFC_VECTORS[1]
        out1, _ = run_tool(["sign", v["secret"], v["msg"]])
        out2, _ = run_tool(["sign", v["secret"], v["msg"]])
        assert out1 == out2, "Signing is not deterministic"


# ── Verification ───────────────────────────────────────────────────────────

class TestVerification:
    @pytest.mark.parametrize("vec_idx", range(len(RFC_VECTORS)))
    def test_rfc_verify_valid(self, vec_idx):
        v = RFC_VECTORS[vec_idx]
        out, rc = run_tool(["verify", v["pubkey"], v["msg"], v["sig"]])
        assert rc == 0
        assert out == "VALID", f"RFC vector {vec_idx}: valid signature rejected"

    def test_tampered_message(self):
        """Flipping a bit in the message must cause rejection."""
        v = RFC_VECTORS[1]  # 1-byte message "72"
        tampered_msg = "73"  # flip bit
        out, _ = run_tool(["verify", v["pubkey"], tampered_msg, v["sig"]])
        assert out == "INVALID", "Tampered message was accepted"

    def test_tampered_message_empty_to_nonempty(self):
        """An empty-message signature must not verify a non-empty message."""
        v = RFC_VECTORS[0]  # empty message
        out, _ = run_tool(["verify", v["pubkey"], "00", v["sig"]])
        assert out == "INVALID", "Empty-message sig accepted for non-empty message"

    def test_tampered_signature_R(self):
        """Flipping a bit in R must cause rejection."""
        v = RFC_VECTORS[2]
        sig = v["sig"]
        # Flip bit in byte 10 of R
        sig_bytes = bytearray(bytes.fromhex(sig))
        sig_bytes[10] ^= 0x01
        tampered_sig = sig_bytes.hex()
        out, _ = run_tool(["verify", v["pubkey"], v["msg"], tampered_sig])
        assert out == "INVALID", "Tampered R was accepted"

    def test_tampered_signature_S(self):
        """Flipping a bit in S must cause rejection."""
        v = RFC_VECTORS[2]
        sig = v["sig"]
        sig_bytes = bytearray(bytes.fromhex(sig))
        sig_bytes[40] ^= 0x02  # byte 40 is in S portion
        tampered_sig = sig_bytes.hex()
        out, _ = run_tool(["verify", v["pubkey"], v["msg"], tampered_sig])
        assert out == "INVALID", "Tampered S was accepted"

    def test_wrong_pubkey(self):
        """Using wrong public key must cause rejection."""
        v0 = RFC_VECTORS[0]
        v1 = RFC_VECTORS[1]
        out, _ = run_tool(["verify", v1["pubkey"], v0["msg"], v0["sig"]])
        assert out == "INVALID", "Wrong public key was accepted"


# ── Malleability Rejection ─────────────────────────────────────────────────

class TestMalleability:
    def test_s_plus_l_rejected(self):
        """Signature with S + L (where S was valid) must be rejected."""
        v = RFC_VECTORS[0]
        sig_bytes = bytes.fromhex(v["sig"])
        R = sig_bytes[:32]
        S = int.from_bytes(sig_bytes[32:], "little")
        S_malleable = S + L
        assert S_malleable < 2**256, "S+L doesn't fit in 32 bytes"
        malleable_sig = (R + S_malleable.to_bytes(32, "little")).hex()
        out, _ = run_tool(["verify", v["pubkey"], v["msg"], malleable_sig])
        assert out == "INVALID", "Malleable signature (S+L) was accepted"

    def test_s_equals_l_rejected(self):
        """Signature with S = L must be rejected."""
        v = RFC_VECTORS[0]
        sig_bytes = bytes.fromhex(v["sig"])
        R = sig_bytes[:32]
        bad_sig = (R + L.to_bytes(32, "little")).hex()
        out, _ = run_tool(["verify", v["pubkey"], v["msg"], bad_sig])
        assert out == "INVALID", "Signature with S=L was accepted"

    def test_s_max_rejected(self):
        """Signature with S = 2^256 - 1 must be rejected."""
        v = RFC_VECTORS[0]
        sig_bytes = bytes.fromhex(v["sig"])
        R = sig_bytes[:32]
        max_s = (2**256 - 1).to_bytes(32, "little")
        bad_sig = (R + max_s).hex()
        out, _ = run_tool(["verify", v["pubkey"], v["msg"], bad_sig])
        assert out == "INVALID", "Signature with S=2^256-1 was accepted"


# ── SUPERCOP Vectors ───────────────────────────────────────────────────────

class TestSupercop:
    @pytest.mark.parametrize("line_idx", range(len(SUPERCOP_LINES)))
    def test_supercop_keygen(self, line_idx):
        secret, pubkey, msg, sig = parse_supercop_line(SUPERCOP_LINES[line_idx])
        out, rc = run_tool(["keygen", secret])
        assert rc == 0
        assert out == pubkey, (
            f"SUPERCOP vec {line_idx}: keygen mismatch. "
            f"Expected {pubkey}, got {out}"
        )

    @pytest.mark.parametrize("line_idx", range(len(SUPERCOP_LINES)))
    def test_supercop_sign(self, line_idx):
        secret, pubkey, msg, sig = parse_supercop_line(SUPERCOP_LINES[line_idx])
        out, rc = run_tool(["sign", secret, msg])
        assert rc == 0
        assert out == sig, (
            f"SUPERCOP vec {line_idx}: sign mismatch.\n"
            f"Expected: {sig}\nGot:      {out}"
        )

    @pytest.mark.parametrize("line_idx", range(len(SUPERCOP_LINES)))
    def test_supercop_verify(self, line_idx):
        secret, pubkey, msg, sig = parse_supercop_line(SUPERCOP_LINES[line_idx])
        out, rc = run_tool(["verify", pubkey, msg, sig])
        assert rc == 0
        assert out == "VALID", f"SUPERCOP vec {line_idx}: valid sig rejected"
