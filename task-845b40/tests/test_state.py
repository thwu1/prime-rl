
import subprocess
import os
import base64


class TestDeserializationExploit:
    def test_exploit_file_exists(self):
        """The exploit generator script must exist at /app/exploit.rb"""
        assert os.path.isfile('/app/exploit.rb'), "/app/exploit.rb must exist"

    def test_exploit_runs_successfully(self):
        """The exploit script must execute without errors"""
        result = subprocess.run(
            ['ruby', '/app/exploit.rb'],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"exploit.rb exited with code {result.returncode}: {result.stderr}"
        )

    def test_exploit_outputs_valid_base64(self):
        """The exploit must output valid base64 data"""
        result = subprocess.run(
            ['ruby', '/app/exploit.rb'],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0
        payload = result.stdout.strip()
        assert len(payload) > 0, "exploit.rb must produce output on stdout"
        try:
            decoded = base64.b64decode(payload, validate=True)
        except Exception as e:
            assert False, f"output is not valid base64: {e}"
        assert len(decoded) > 4, "decoded payload is too small to be valid Marshal data"

    def test_payload_has_marshal_magic_bytes(self):
        """The payload must be valid Ruby Marshal data (magic bytes 0x04 0x08)"""
        result = subprocess.run(
            ['ruby', '/app/exploit.rb'],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0
        payload = result.stdout.strip()
        decoded = base64.b64decode(payload)
        assert decoded[0:2] == b'\x04\x08', (
            f"payload does not start with Marshal magic bytes 0x04 0x08 "
            f"(got 0x{decoded[0]:02x} 0x{decoded[1]:02x})"
        )

    def test_exploit_uses_marshal_dump(self):
        """The exploit must construct a gadget chain using Marshal.dump"""
        with open('/app/exploit.rb', 'r') as f:
            code = f.read()
        assert 'Marshal.dump' in code, (
            "exploit.rb must use Marshal.dump to serialize a gadget chain"
        )

    def test_exploit_does_not_create_file_directly(self):
        """Running exploit.rb must NOT create pwned.txt - only deserialization should"""
        if os.path.exists('/app/pwned.txt'):
            os.remove('/app/pwned.txt')

        result = subprocess.run(
            ['ruby', '/app/exploit.rb'],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"exploit.rb failed: {result.stderr}"
        assert not os.path.isfile('/app/pwned.txt'), (
            "exploit.rb must not directly create /app/pwned.txt - "
            "it should only output a serialized payload"
        )

    def test_deserialization_achieves_rce(self):
        """Deserializing the payload must create /app/pwned.txt via gadget chain"""
        if os.path.exists('/app/pwned.txt'):
            os.remove('/app/pwned.txt')

        # Generate payload
        gen = subprocess.run(
            ['ruby', '/app/exploit.rb'],
            capture_output=True, text=True, timeout=30
        )
        assert gen.returncode == 0, f"exploit.rb failed: {gen.stderr}"
        payload = gen.stdout.strip()
        assert len(payload) > 0, "exploit.rb produced no output"

        # Deserialize payload using the application's deserializer
        deser = subprocess.run(
            ['ruby', '/app/deserialize.rb', payload],
            capture_output=True, text=True, timeout=30
        )

        # Verify RCE - the gadget chain must have executed touch /app/pwned.txt
        assert os.path.isfile('/app/pwned.txt'), (
            "deserialization did not create /app/pwned.txt - "
            "the gadget chain did not achieve code execution. "
            f"deserialize stderr: {deser.stderr}"
        )
