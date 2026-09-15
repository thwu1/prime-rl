
import json
import os
import pytest

REPORT_PATH = "/app/audit_report.json"

# Expected results keyed by filename
EXPECTED = {
    "bab0v7jb1pmgj5vs65wyjy87cr4vmhpj.narinfo": {
        "status": "valid",
        "store_path": "/nix/store/bab0v7jb1pmgj5vs65wyjy87cr4vmhpj-hello-2.12.3.tar.gz",
        "computed_path": "/nix/store/bab0v7jb1pmgj5vs65wyjy87cr4vmhpj-hello-2.12.3.tar.gz",
        "content_hash_hex": "c149573c77f04b8a62755d5b36bd9016edd2fff818e01fd6d507ca60c9723fec",
        "content_hash_nix32": "1v1zfb4n1jh7spb1zq0qz3zx5v8nj2ykcnsxfmi8ljzhfwy5fjf1",
        "content_hash_sri": "sha256-wUlXPHfwS4pidV1bNr2QFu3S//gY4B/W1QfKYMlyP+w=",
        "derivation_type": "flat",
    },
    "3qmynwqqmmv89509j334y7zhlppnjig9.narinfo": {
        "status": "valid",
        "store_path": "/nix/store/3qmynwqqmmv89509j334y7zhlppnjig9-source",
        "computed_path": "/nix/store/3qmynwqqmmv89509j334y7zhlppnjig9-source",
        "content_hash_hex": "0a244927f7dba91b04757adf86ac41fd7f2933c7f9f22cc08413577d59db509c",
        "content_hash_nix32": "172hvdcpsmqkhk02rwprqwrjjzzx86n8dpvsfl21pafvywklj90a",
        "content_hash_sri": "sha256-CiRJJ/fbqRsEdXrfhqxB/X8pM8f58izAhBNXfVnbUJw=",
        "derivation_type": "recursive",
    },
    "bbfs5nsa0xf82j7bq8qkh8s1zvzxnrwd.narinfo": {
        "status": "valid",
        "store_path": "/nix/store/bbfs5nsa0xf82j7bq8qkh8s1zvzxnrwd-builder.sh",
        "computed_path": "/nix/store/bbfs5nsa0xf82j7bq8qkh8s1zvzxnrwd-builder.sh",
        "content_hash_hex": "d34d1c015c0b86c7ffe965c3e0d63ea17d018a83a5a00b6a88f980c9857ffb66",
        "content_hash_nix32": "0rpvgy2wk07ri1m0p855hf502zd17vbf1hv5x7zwg1hbbh0iqkfk",
        "content_hash_sri": "sha256-000cAVwLhsf/6WXD4NY+oX0BioOloAtqiPmAyYV/+2Y=",
        "derivation_type": "text",
    },
    "ly7x20h637pg9b0lnycfqkdqwppiv16z.narinfo": {
        "status": "valid",
        "store_path": "/nix/store/ly7x20h637pg9b0lnycfqkdqwppiv16z-coreutils-9.4.tar.xz",
        "computed_path": "/nix/store/ly7x20h637pg9b0lnycfqkdqwppiv16z-coreutils-9.4.tar.xz",
        "content_hash_hex": "a194196aed3725110714ae25c5bec4a9d9153ba330ed4382b561c4a191ce1379",
        "content_hash_nix32": "0y8krs8s3i31nn147v9hlcxibnd9qjzca9df2h3i299pxmm1k551",
        "content_hash_sri": "sha256-oZQZau03JREHFK4lxb7EqdkVO6Mw7UOCtWHEoZHOE3k=",
        "derivation_type": "flat",
    },
    "zsp60hn424jza9hs5k668g1hlyyr0lvr.narinfo": {
        "status": "valid",
        "store_path": "/nix/store/zsp60hn424jza9hs5k668g1hlyyr0lvr-openssl-3.2.1-src",
        "computed_path": "/nix/store/zsp60hn424jza9hs5k668g1hlyyr0lvr-openssl-3.2.1-src",
        "content_hash_hex": "97e0f07a2dc5abf86f9557ce11070dc4999e04ef393bd3bceafc02c9cd1cbdce",
        "content_hash_nix32": "1kmx3k6wj0pwxayd6frrxw29x6f41l3i3kjpjmpziay55mxg1q4p",
        "content_hash_sri": "sha256-l+Dwei3Fq/hvlVfOEQcNxJmeBO85O9O86vwCyc0cvc4=",
        "derivation_type": "recursive",
    },
    "i057ghfyd7d1vnzi5kswaz5i67xyma5n.narinfo": {
        "status": "valid",
        "store_path": "/nix/store/i057ghfyd7d1vnzi5kswaz5i67xyma5n-setup-hook.sh",
        "computed_path": "/nix/store/i057ghfyd7d1vnzi5kswaz5i67xyma5n-setup-hook.sh",
        "content_hash_hex": "dc0d5e176f63390762334568d969c7d3f76ac97aeed5519428b03139a2f967fa",
        "content_hash_nix32": "1yk7z6i3jcdh52a53mgfgb4nmxykqxlxjs256di0ffb3dwbmw3fw",
        "content_hash_sri": "sha256-3A1eF29jOQdiM0Vo2WnH0/dqyXru1VGUKLAxOaL5Z/o=",
        "derivation_type": "text",
    },
    "mzl6wij0clyy7fir27v1333cv1pc2vk2.narinfo": {
        "status": "path_mismatch",
        "store_path": "/nix/store/mzl6wij0clyy7fir27v1333cv1pc2vk2-zlib-1.3.1.tar.gz",
        "computed_path": "/nix/store/dirl87430zjvmh7s2vrfnc4c3w5ivybd-zlib-1.3.1.tar.gz",
        "content_hash_hex": "81d053b217275b5a617c847224ca90ddcf34053a0c89a7e149d4f082226dec69",
        "content_hash_nix32": "0sgcdli85w6l97hsg28c782k9kyxj3528wl4gihmlnr72yr57l41",
        "content_hash_sri": "sha256-gdBTshcnW1phfIRyJMqQ3c80BToMiafhSdTwgiJt7Gk=",
        "derivation_type": "flat",
    },
    "wl3wkqg7zhk3d9jlznqd797grsjlq3sm.narinfo": {
        "status": "path_mismatch",
        "store_path": "/nix/store/wl3wkqg7zhk3d9jlznqd797grsjlq3sm-python-3.12.2-src",
        "computed_path": "/nix/store/xkdgmyfj9kmk7qz3mrxmvz0fsmw9sblp-python-3.12.2-src",
        "content_hash_hex": "e3f3708320fc44b81c2fa58aed432dafc7f6b2033016fc174b444432036d2b50",
        "content_hash_nix32": "0l1bdl1k4i249cbzq5ih0frgdixg5m1yv2m55wfbhi7w421p1wz3",
        "content_hash_sri": "sha256-4/NwgyD8RLgcL6WK7UMtr8f2sgMwFvwXS0REMgNtK1A=",
        "derivation_type": "recursive",
    },
    "nmac30dl01swhf2slkw6i5xjsyl28pbh.narinfo": {
        "status": "path_mismatch",
        "store_path": "/nix/store/nmac30dl01swhf2slkw6i5xjsyl28pbh-configure",
        "computed_path": "/nix/store/01ilcdfcgygafalqk1a4b5012baypw53-configure",
        "content_hash_hex": "d095c62acfdfd331680073c902b0f6738c24d7df865232b27f1de5935283abe0",
        "content_hash_nix32": "1q5bhd997r8xgyr34ll6vzbj933kysq05jbk01l33lyzrwmcd5fh",
        "content_hash_sri": "sha256-0JXGKs/f0zFoAHPJArD2c4wk19+GUjKyfx3lk1KDq+A=",
        "derivation_type": "text",
    },
    "00000000000000000000000000000000.narinfo": {
        "status": "hash_format_error",
        "store_path": "/nix/store/00000000000000000000000000000000-curl-8.5.0.tar.xz",
        "computed_path": None,
        "content_hash_hex": None,
        "content_hash_nix32": None,
        "content_hash_sri": None,
        "derivation_type": "flat",
    },
    "11111111111111111111111111111111.narinfo": {
        "status": "hash_format_error",
        "store_path": "/nix/store/11111111111111111111111111111111-wget-1.24.tar.gz",
        "computed_path": None,
        "content_hash_hex": None,
        "content_hash_nix32": None,
        "content_hash_sri": None,
        "derivation_type": "flat",
    },
    "22222222222222222222222222222222.narinfo": {
        "status": "hash_format_error",
        "store_path": "/nix/store/22222222222222222222222222222222-vim-9.1.tar.gz",
        "computed_path": None,
        "content_hash_hex": None,
        "content_hash_nix32": None,
        "content_hash_sri": None,
        "derivation_type": "recursive",
    },
    "9gikrkkngm7nq8dlqjzyzziqrz503cm4.narinfo": {
        "status": "type_inconsistency",
        "store_path": "/nix/store/9gikrkkngm7nq8dlqjzyzziqrz503cm4-git-2.44.0-src",
        "computed_path": "/nix/store/ql034ijid390ry5q928pnk9sxr54qffw-git-2.44.0-src",
        "content_hash_hex": "5460df6c699f7d2fdba6dbeb57d5a53ad5eb93eb2fad9516ebd9489168f233e8",
        "content_hash_nix32": "1s1ky9l92j6rxcb9bb9gxf9ypm9slpamgsyvlvdjyzczd5ndyq2l",
        "content_hash_sri": "sha256-VGDfbGmffS/bptvrV9WlOtXrk+svrZUW69lIkWjyM+g=",
        "derivation_type": "flat",
    },
    "aczb0zlrp8hal9f90spk6xyhcqg3ivax.narinfo": {
        "status": "type_inconsistency",
        "store_path": "/nix/store/aczb0zlrp8hal9f90spk6xyhcqg3ivax-bash-5.2.21.tar.gz",
        "computed_path": "/nix/store/xqdnly60s04gv4f6nfzqghkc6aiczlvc-bash-5.2.21.tar.gz",
        "content_hash_hex": "28e1c21f44ebf9950db5ab81c72f9713193af088b6975b3bc7984a29e8f03c9e",
        "content_hash_nix32": "17iwy3l2jjlqqwxmp5xni3q3l68kjwpwg0dbnl6rbygb8hgw5q98",
        "content_hash_sri": "sha256-KOHCH0Tr+ZUNtauBxy+XExk68Ii2l1s7x5hKKejwPJ4=",
        "derivation_type": "recursive",
    },
    "8hhs2p1m413bqlz8kayk5dn4xagjkymc.narinfo": {
        "status": "type_inconsistency",
        "store_path": "/nix/store/8hhs2p1m413bqlz8kayk5dn4xagjkymc-libxml2-2.12.5-src",
        "computed_path": "/nix/store/jkm5sidpil7d0c0rsq1lxnz72ldlidyd-libxml2-2.12.5-src",
        "content_hash_hex": "33a2da7c454eaca246429e49baa002bb61d5f8f7478efc4f49f4447eca8fa7a1",
        "content_hash_nix32": "18d7iz57wi7l957zr3j7yzwdaqdv0ahbljcy893a5b2f8mydm8ik",
        "content_hash_sri": "sha256-M6LafEVOrKJGQp5JuqACu2HV+PdHjvxPSfREfsqPp6E=",
        "derivation_type": "text",
    },
    "33333333333333333333333333333333.narinfo": {
        "status": "missing_field",
        "store_path": "/nix/store/33333333333333333333333333333333-ncurses-6.4.tar.gz",
        "computed_path": None,
        "content_hash_hex": None,
        "content_hash_nix32": None,
        "content_hash_sri": None,
        "derivation_type": None,
    },
}

EXPECTED_SUMMARY = {
    "total": 16,
    "valid": 6,
    "path_mismatch": 3,
    "hash_format_error": 3,
    "type_inconsistency": 3,
    "missing_field": 1,
}


@pytest.fixture(scope="module")
def report():
    """Load the audit report once for all tests."""
    assert os.path.isfile(REPORT_PATH), (
        f"{REPORT_PATH} does not exist. Did the auditor run?"
    )
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


def test_report_has_audit_results(report):
    """Report must contain audit_results array."""
    assert "audit_results" in report, "Missing 'audit_results' key"
    assert isinstance(report["audit_results"], list), "audit_results must be a list"


def test_report_has_summary(report):
    """Report must contain summary object."""
    assert "summary" in report, "Missing 'summary' key"
    assert isinstance(report["summary"], dict), "summary must be an object"


def test_entry_count(report):
    """Must have exactly 16 audit result entries."""
    assert len(report["audit_results"]) == 16, (
        f"Expected 16 entries, got {len(report['audit_results'])}"
    )


def test_all_filenames_present(report):
    """All expected narinfo filenames must be present."""
    found = {e["filename"] for e in report["audit_results"]}
    expected_fnames = set(EXPECTED.keys())
    missing = expected_fnames - found
    extra = found - expected_fnames
    assert not missing, f"Missing entries: {missing}"
    assert not extra, f"Unexpected entries: {extra}"


def test_entries_sorted_by_filename(report):
    """Entries must be sorted by filename."""
    filenames = [e["filename"] for e in report["audit_results"]]
    assert filenames == sorted(filenames), "audit_results must be sorted by filename"


def test_required_fields(report):
    """Each entry must have all required fields."""
    required = {
        "filename", "status", "store_path", "computed_path",
        "content_hash_hex", "content_hash_nix32", "content_hash_sri",
        "derivation_type", "error_detail",
    }
    for entry in report["audit_results"]:
        missing = required - set(entry.keys())
        assert not missing, (
            f"Entry {entry.get('filename', '?')}: missing fields {missing}"
        )


@pytest.mark.parametrize("filename", list(EXPECTED.keys()))
def test_status_classification(report, filename):
    """Each entry must have the correct status."""
    entry = next(e for e in report["audit_results"] if e["filename"] == filename)
    exp = EXPECTED[filename]
    assert entry["status"] == exp["status"], (
        f"{filename}: expected status '{exp['status']}', got '{entry['status']}'"
    )


@pytest.mark.parametrize("filename", list(EXPECTED.keys()))
def test_store_path(report, filename):
    """Each entry must report the correct store_path from narinfo."""
    entry = next(e for e in report["audit_results"] if e["filename"] == filename)
    exp = EXPECTED[filename]
    assert entry["store_path"] == exp["store_path"], (
        f"{filename}: store_path mismatch"
    )


@pytest.mark.parametrize("filename", list(EXPECTED.keys()))
def test_computed_path(report, filename):
    """Each entry must have the correct computed_path."""
    entry = next(e for e in report["audit_results"] if e["filename"] == filename)
    exp = EXPECTED[filename]
    assert entry["computed_path"] == exp["computed_path"], (
        f"{filename}: expected computed_path '{exp['computed_path']}', "
        f"got '{entry['computed_path']}'"
    )


@pytest.mark.parametrize("filename", list(EXPECTED.keys()))
def test_content_hash_hex(report, filename):
    """Each entry must have the correct hex hash conversion."""
    entry = next(e for e in report["audit_results"] if e["filename"] == filename)
    exp = EXPECTED[filename]
    assert entry["content_hash_hex"] == exp["content_hash_hex"], (
        f"{filename}: hex hash mismatch"
    )


@pytest.mark.parametrize("filename", list(EXPECTED.keys()))
def test_content_hash_nix32(report, filename):
    """Each entry must have the correct nix32 hash conversion."""
    entry = next(e for e in report["audit_results"] if e["filename"] == filename)
    exp = EXPECTED[filename]
    assert entry["content_hash_nix32"] == exp["content_hash_nix32"], (
        f"{filename}: nix32 hash mismatch"
    )


@pytest.mark.parametrize("filename", list(EXPECTED.keys()))
def test_content_hash_sri(report, filename):
    """Each entry must have the correct SRI hash conversion."""
    entry = next(e for e in report["audit_results"] if e["filename"] == filename)
    exp = EXPECTED[filename]
    assert entry["content_hash_sri"] == exp["content_hash_sri"], (
        f"{filename}: SRI hash mismatch"
    )


@pytest.mark.parametrize("filename", list(EXPECTED.keys()))
def test_derivation_type(report, filename):
    """Each entry must report the correct derivation_type."""
    entry = next(e for e in report["audit_results"] if e["filename"] == filename)
    exp = EXPECTED[filename]
    assert entry["derivation_type"] == exp["derivation_type"], (
        f"{filename}: derivation_type mismatch"
    )


def test_summary_total(report):
    """Summary total must match entry count."""
    assert report["summary"]["total"] == EXPECTED_SUMMARY["total"], (
        f"Summary total: expected {EXPECTED_SUMMARY['total']}, "
        f"got {report['summary']['total']}"
    )


def test_summary_valid_count(report):
    """Summary valid count must be correct."""
    assert report["summary"]["valid"] == EXPECTED_SUMMARY["valid"]


def test_summary_path_mismatch_count(report):
    """Summary path_mismatch count must be correct."""
    assert report["summary"]["path_mismatch"] == EXPECTED_SUMMARY["path_mismatch"]


def test_summary_hash_format_error_count(report):
    """Summary hash_format_error count must be correct."""
    assert report["summary"]["hash_format_error"] == EXPECTED_SUMMARY["hash_format_error"]


def test_summary_type_inconsistency_count(report):
    """Summary type_inconsistency count must be correct."""
    assert report["summary"]["type_inconsistency"] == EXPECTED_SUMMARY["type_inconsistency"]


def test_summary_missing_field_count(report):
    """Summary missing_field count must be correct."""
    assert report["summary"]["missing_field"] == EXPECTED_SUMMARY["missing_field"]


def test_valid_entries_have_null_error_detail(report):
    """Valid entries must have error_detail set to null."""
    for entry in report["audit_results"]:
        if entry["status"] == "valid":
            assert entry["error_detail"] is None, (
                f"{entry['filename']}: valid entry should have null error_detail"
            )


def test_invalid_entries_have_error_detail(report):
    """Non-valid entries must have a non-null error_detail string."""
    for entry in report["audit_results"]:
        if entry["status"] != "valid":
            assert entry["error_detail"] is not None, (
                f"{entry['filename']}: invalid entry should have error_detail"
            )
            assert isinstance(entry["error_detail"], str), (
                f"{entry['filename']}: error_detail must be a string"
            )
            assert len(entry["error_detail"]) > 0, (
                f"{entry['filename']}: error_detail must not be empty"
            )
