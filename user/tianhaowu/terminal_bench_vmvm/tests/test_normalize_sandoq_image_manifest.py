import hashlib
import json

import pytest
from normalize_sandoq_image_manifest import derive_manifest, normalize_reference


def test_normalize_reference_preserves_repository_and_digest() -> None:
    digest = "a" * 64
    assert (
        normalize_reference(f"registry.example:5000/team/image:approved@sha256:{digest}")
        == f"registry.example:5000/team/image@sha256:{digest}"
    )
    assert (
        normalize_reference(f"registry.example:5000/team/image@sha256:{digest}")
        == f"registry.example:5000/team/image@sha256:{digest}"
    )


def test_derive_manifest_is_deterministic_and_binds_source_sha() -> None:
    source = {
        "schema_version": 3,
        "images": {
            "opaque-a": {
                "agent": "registry.example/a:tag@sha256:" + "a" * 64,
                "digest": "sha256:" + "a" * 64,
            },
            "opaque-b": {
                "agent": "registry.example/b:tag@sha256:" + "b" * 64,
                "verifier": "registry.example/v:tag@sha256:" + "c" * 64,
            },
        },
    }
    source_payload = json.dumps(source).encode()
    source_sha = hashlib.sha256(source_payload).hexdigest()

    first = derive_manifest(source_payload, source_sha)
    second = derive_manifest(source_payload, source_sha)
    result = json.loads(first)

    assert first == second
    assert result["sandoq_normalization"]["source_sha256"] == source_sha
    assert result["sandoq_normalization"]["normalized_roles"] == 3
    assert result["images"]["opaque-a"]["agent"].endswith("@sha256:" + "a" * 64)
    assert ":tag@" not in result["images"]["opaque-a"]["agent"]


def test_derive_manifest_rejects_source_sha_mismatch() -> None:
    payload = json.dumps({"images": {}}).encode()
    with pytest.raises(ValueError, match="approved input"):
        derive_manifest(payload, "0" * 64)


@pytest.mark.parametrize(
    "reference",
    [
        "registry.example/image:latest",
        "registry.example/image@sha256:short",
        "registry.example/image:@sha256:" + "a" * 64,
    ],
)
def test_normalize_reference_rejects_mutable_or_invalid_references(
    reference: str,
) -> None:
    with pytest.raises(ValueError):
        normalize_reference(reference)
