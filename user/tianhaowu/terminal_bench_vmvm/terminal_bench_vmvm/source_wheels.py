"""Fail-closed policy and artifact validation for oracle source-wheel recovery."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import tarfile
import uuid
from dataclasses import asdict, dataclass
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile

SOURCE_WHEEL_POLICY_SCHEMA_VERSION = 1
SOURCE_WHEEL_ATTESTATION_SCHEMA_VERSION = 1
MAX_SOURCE_INPUT_BYTES = 256 * 1024 * 1024
MAX_WHEEL_BYTES = 256 * 1024 * 1024
MAX_WHEELHOUSE_BYTES = 1024 * 1024 * 1024
MAX_WHEEL_FILES = 256
MAX_WHEEL_MEMBERS = 20_000
MAX_WHEEL_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_SDIST_MEMBERS = 20_000
MAX_SDIST_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_IMAGE_DIGEST_RE = re.compile(r"[^\s@]+(?:[:][^\s@]+)?@sha256:[0-9a-f]{64}")
_SAFE_FILENAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]*")
_EXACT_REQUIREMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9.!+_-]+")
_SDIST_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz", ".zip")


def canonical_json(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def strict_json_loads(payload: bytes | str) -> object:
    """Decode JSON while rejecting ambiguous keys and non-finite numbers."""

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON object key")
            value[key] = item
        return value

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    return json.loads(
        payload,
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def is_digest_pinned_image(image: str) -> bool:
    return _IMAGE_DIGEST_RE.fullmatch(image) is not None


@dataclass(frozen=True)
class SourceArtifactPolicy:
    distribution: str
    version: str
    filename: str
    url: str
    size: int
    sha256: str
    wheel_filename: str
    wheel_size: int
    wheel_sha256: str


@dataclass(frozen=True)
class BinaryWheelPolicy:
    distribution: str
    version: str
    filename: str
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class SourceWheelPolicyEntry:
    requirements: tuple[str, ...]
    image: str
    build_tools: tuple[tuple[str, str], ...]
    sources: tuple[SourceArtifactPolicy, ...]
    binary_wheels: tuple[BinaryWheelPolicy, ...]

    @property
    def expected_wheels(self) -> tuple[tuple[str, str, str, int, str], ...]:
        wheels = [
            (
                source.distribution,
                source.version,
                source.wheel_filename,
                source.wheel_size,
                source.wheel_sha256,
            )
            for source in self.sources
        ]
        wheels.extend(
            (wheel.distribution, wheel.version, wheel.filename, wheel.size, wheel.sha256)
            for wheel in self.binary_wheels
        )
        return tuple(sorted(wheels, key=lambda item: item[2]))


@dataclass(frozen=True)
class SourceWheelPolicy:
    path: Path
    sha256: str
    allowed_hosts: tuple[str, ...]
    entries: tuple[SourceWheelPolicyEntry, ...]

    def entry_for(
        self,
        requirements: tuple[str, ...],
        image: str,
        build_tools: tuple[tuple[str, str], ...],
    ) -> SourceWheelPolicyEntry:
        candidates = [entry for entry in self.entries if entry.requirements == requirements and entry.image == image]
        if not candidates:
            raise RuntimeError("source-wheel recovery is not allowlisted for this requirement/image pair")
        entry = candidates[0]
        if entry.build_tools != build_tools:
            raise RuntimeError("source-wheel builder tools do not match the approved image-pinned toolchain")
        return entry


@dataclass(frozen=True)
class WheelEvidence:
    distribution: str
    version: str
    filename: str
    size: int
    sha256: str
    universal: bool


def _require_exact_keys(value: dict, expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} must contain exactly {sorted(expected)}")


def _validated_filename(value: object, label: str, *, suffixes: tuple[str, ...]) -> str:
    if not isinstance(value, str) or _SAFE_FILENAME_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a safe basename")
    if not value.lower().endswith(suffixes):
        raise ValueError(f"{label} has an unsupported artifact suffix")
    return value


def _validated_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _validated_size(value: object, label: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > maximum:
        raise ValueError(f"{label} must be between 1 and {maximum} bytes")
    return value


def _validated_distribution(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or canonical_distribution_name(value) != value:
        raise ValueError(f"{label} must be a canonical distribution name")
    return value


def _validated_version(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or any(character.isspace() for character in value):
        raise ValueError(f"{label} must be a nonempty version without whitespace")
    return value


def _validated_url(value: object, allowed_hosts: set[str], label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an HTTPS URL")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError(f"{label} must be an HTTPS URL") from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{label} must be a credential-free HTTPS URL on an approved host")
    return value


def _parse_source(
    raw: object,
    allowed_hosts: set[str],
    label: str,
) -> SourceArtifactPolicy:
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be an object")
    _require_exact_keys(
        raw,
        {
            "distribution",
            "version",
            "filename",
            "url",
            "size",
            "sha256",
            "wheel_filename",
            "wheel_size",
            "wheel_sha256",
        },
        label,
    )
    return SourceArtifactPolicy(
        distribution=_validated_distribution(raw["distribution"], f"{label}.distribution"),
        version=_validated_version(raw["version"], f"{label}.version"),
        filename=_validated_filename(raw["filename"], f"{label}.filename", suffixes=_SDIST_SUFFIXES),
        url=_validated_url(raw["url"], allowed_hosts, f"{label}.url"),
        size=_validated_size(raw["size"], f"{label}.size", MAX_SOURCE_INPUT_BYTES),
        sha256=_validated_sha256(raw["sha256"], f"{label}.sha256"),
        wheel_filename=_validated_filename(
            raw["wheel_filename"],
            f"{label}.wheel_filename",
            suffixes=(".whl",),
        ),
        wheel_size=_validated_size(raw["wheel_size"], f"{label}.wheel_size", MAX_WHEEL_BYTES),
        wheel_sha256=_validated_sha256(raw["wheel_sha256"], f"{label}.wheel_sha256"),
    )


def _parse_binary_wheel(
    raw: object,
    allowed_hosts: set[str],
    label: str,
) -> BinaryWheelPolicy:
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be an object")
    _require_exact_keys(raw, {"distribution", "version", "filename", "url", "size", "sha256"}, label)
    return BinaryWheelPolicy(
        distribution=_validated_distribution(raw["distribution"], f"{label}.distribution"),
        version=_validated_version(raw["version"], f"{label}.version"),
        filename=_validated_filename(raw["filename"], f"{label}.filename", suffixes=(".whl",)),
        url=_validated_url(raw["url"], allowed_hosts, f"{label}.url"),
        size=_validated_size(raw["size"], f"{label}.size", MAX_WHEEL_BYTES),
        sha256=_validated_sha256(raw["sha256"], f"{label}.sha256"),
    )


def load_source_wheel_policy(path: Path, expected_sha256: str) -> SourceWheelPolicy:
    payload = path.read_bytes()
    observed_sha256 = sha256_bytes(payload)
    if observed_sha256 != expected_sha256:
        raise ValueError("source-wheel policy SHA-256 mismatch")

    try:
        raw = strict_json_loads(payload)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise ValueError("source-wheel policy is not valid JSON") from error
    if not isinstance(raw, dict):
        raise ValueError("source-wheel policy must be an object")
    _require_exact_keys(raw, {"schema_version", "allowed_hosts", "entries"}, "source-wheel policy")
    if raw["schema_version"] != SOURCE_WHEEL_POLICY_SCHEMA_VERSION:
        raise ValueError("unsupported source-wheel policy schema")
    hosts = raw["allowed_hosts"]
    if (
        not isinstance(hosts, list)
        or not hosts
        or not all(isinstance(host, str) and host and host == host.lower() for host in hosts)
        or len(hosts) != len(set(hosts))
    ):
        raise ValueError("source-wheel policy allowed_hosts must be unique lowercase hostnames")
    allowed_hosts = set(hosts)
    raw_entries = raw["entries"]
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError("source-wheel policy entries must be a nonempty list")
    entries: list[SourceWheelPolicyEntry] = []
    keys: set[tuple[tuple[str, ...], str]] = set()
    for entry_index, raw_entry in enumerate(raw_entries):
        label = f"source-wheel policy entry {entry_index}"
        if not isinstance(raw_entry, dict):
            raise ValueError(f"{label} must be an object")
        _require_exact_keys(
            raw_entry,
            {"requirements", "image", "build_tools", "sources", "binary_wheels"},
            label,
        )
        requirements = raw_entry["requirements"]
        if (
            not isinstance(requirements, list)
            or not requirements
            or not all(isinstance(item, str) and _EXACT_REQUIREMENT_RE.fullmatch(item) for item in requirements)
            or len(requirements) != len(set(requirements))
        ):
            raise ValueError(f"{label}.requirements must contain unique exact pins")
        requirement_tuple = tuple(requirements)
        image = raw_entry["image"]
        if not isinstance(image, str) or not is_digest_pinned_image(image):
            raise ValueError(f"{label}.image must be an immutable digest-pinned reference")
        tools = raw_entry["build_tools"]
        if not isinstance(tools, dict) or set(tools) != {"pip", "setuptools", "wheel"}:
            raise ValueError(f"{label}.build_tools must pin pip, setuptools, and wheel")
        if not all(
            isinstance(value, str) and value and not any(c.isspace() for c in value) for value in tools.values()
        ):
            raise ValueError(f"{label}.build_tools values must be exact nonempty versions")
        build_tools = tuple(sorted((str(key), str(value)) for key, value in tools.items()))
        raw_sources = raw_entry["sources"]
        raw_binary_wheels = raw_entry["binary_wheels"]
        if not isinstance(raw_sources, list) or len(raw_sources) != 1:
            raise ValueError(f"{label}.sources must contain exactly one source artifact")
        if not isinstance(raw_binary_wheels, list):
            raise ValueError(f"{label}.binary_wheels must be a list")
        sources = tuple(
            _parse_source(source, allowed_hosts, f"{label}.sources[{index}]")
            for index, source in enumerate(raw_sources)
        )
        binary_wheels = tuple(
            _parse_binary_wheel(wheel, allowed_hosts, f"{label}.binary_wheels[{index}]")
            for index, wheel in enumerate(raw_binary_wheels)
        )
        input_filenames = [source.filename for source in sources]
        input_filenames.extend(wheel.filename for wheel in binary_wheels)
        output_filenames = [source.wheel_filename for source in sources]
        output_filenames.extend(wheel.filename for wheel in binary_wheels)
        if len(input_filenames) != len(set(input_filenames)):
            raise ValueError(f"{label} has duplicate input filenames")
        if len(output_filenames) != len(set(output_filenames)):
            raise ValueError(f"{label} has duplicate wheel filenames")
        closure = {(source.distribution, source.version) for source in sources} | {
            (wheel.distribution, wheel.version) for wheel in binary_wheels
        }
        if len(closure) != len(output_filenames):
            raise ValueError(f"{label} has duplicate distributions in its wheel closure")
        for requirement in requirement_tuple:
            name, _, version = requirement.partition("==")
            name = name.partition("[")[0]
            if (canonical_distribution_name(name), version) not in closure:
                raise ValueError(f"{label} omits a root requirement from its wheel closure")
        key = (requirement_tuple, image)
        if key in keys:
            raise ValueError(f"{label} duplicates a requirement/image policy entry")
        keys.add(key)
        entries.append(
            SourceWheelPolicyEntry(
                requirements=requirement_tuple,
                image=image,
                build_tools=build_tools,
                sources=sources,
                binary_wheels=binary_wheels,
            )
        )
    return SourceWheelPolicy(
        path=path.resolve(),
        sha256=observed_sha256,
        allowed_hosts=tuple(hosts),
        entries=tuple(entries),
    )


def _safe_archive_member(name: str) -> bool:
    if "\\" in name:
        return False
    path = PurePosixPath(name)
    return bool(path.parts) and not path.is_absolute() and ".." not in path.parts


def inspect_wheel(filename: str, payload: bytes) -> WheelEvidence:
    if len(payload) < 1 or len(payload) > MAX_WHEEL_BYTES:
        raise RuntimeError("wheel payload exceeds the bounded size contract")
    digest = sha256_bytes(payload)
    try:
        with ZipFile(io.BytesIO(payload)) as wheel:
            members = wheel.infolist()
            if not members or len(members) > MAX_WHEEL_MEMBERS:
                raise RuntimeError("wheel has an invalid member count")
            total_size = 0
            metadata_members = []
            wheel_members = []
            for member in members:
                member_mode = member.external_attr >> 16
                if not _safe_archive_member(member.filename) or member.flag_bits & 0x1 or stat.S_ISLNK(member_mode):
                    raise RuntimeError("wheel contains an unsafe archive member")
                if member.file_size < 0 or member.file_size > MAX_WHEEL_UNCOMPRESSED_BYTES:
                    raise RuntimeError("wheel member exceeds the bounded size contract")
                total_size += member.file_size
                if total_size > MAX_WHEEL_UNCOMPRESSED_BYTES:
                    raise RuntimeError("wheel exceeds the bounded expansion contract")
                if member.filename.endswith(".dist-info/METADATA"):
                    metadata_members.append(member)
                elif member.filename.endswith(".dist-info/WHEEL"):
                    wheel_members.append(member)
            if len(metadata_members) != 1 or len(wheel_members) != 1:
                raise RuntimeError("wheel must contain exactly one WHEEL and METADATA record")
            metadata_member = metadata_members[0]
            wheel_member = wheel_members[0]
            if PurePosixPath(metadata_member.filename).parent != PurePosixPath(wheel_member.filename).parent:
                raise RuntimeError("wheel metadata records belong to different distributions")
            if metadata_member.file_size > MAX_METADATA_BYTES or wheel_member.file_size > MAX_METADATA_BYTES:
                raise RuntimeError("wheel metadata exceeds the bounded size contract")
            metadata = BytesParser().parsebytes(wheel.read(metadata_member))
            wheel_metadata = BytesParser().parsebytes(wheel.read(wheel_member))
    except RuntimeError:
        raise
    except (BadZipFile, OSError) as error:
        raise RuntimeError("wheel archive validation failed") from error
    except Exception as error:
        raise RuntimeError("wheel archive validation failed") from error
    names = metadata.get_all("Name", [])
    versions = metadata.get_all("Version", [])
    wheel_versions = wheel_metadata.get_all("Wheel-Version", [])
    tags = wheel_metadata.get_all("Tag", [])
    if len(names) != 1 or len(versions) != 1 or len(wheel_versions) != 1 or not tags:
        raise RuntimeError("wheel metadata is incomplete or ambiguous")
    distribution = canonical_distribution_name(names[0].strip())
    version = versions[0].strip()
    if not distribution or not version or not wheel_versions[0].startswith("1."):
        raise RuntimeError("wheel metadata is invalid")
    return WheelEvidence(
        distribution=distribution,
        version=version,
        filename=filename,
        size=len(payload),
        sha256=digest,
        universal=all(tag.strip().endswith("-none-any") for tag in tags),
    )


def inspect_source_distribution(
    source: SourceArtifactPolicy,
    payload: bytes,
) -> None:
    if len(payload) != source.size or sha256_bytes(payload) != source.sha256:
        raise RuntimeError("source distribution does not match its approved size and SHA-256")
    metadata_payloads: list[bytes] = []
    total_size = 0
    if source.filename.lower().endswith(".zip"):
        try:
            with ZipFile(io.BytesIO(payload)) as archive:
                members = archive.infolist()
                if not members or len(members) > MAX_SDIST_MEMBERS:
                    raise RuntimeError("source distribution has an invalid member count")
                for member in members:
                    member_mode = member.external_attr >> 16
                    if not _safe_archive_member(member.filename) or member.flag_bits & 0x1 or stat.S_ISLNK(member_mode):
                        raise RuntimeError("source distribution contains an unsafe archive member")
                    total_size += member.file_size
                    if total_size > MAX_SDIST_UNCOMPRESSED_BYTES:
                        raise RuntimeError("source distribution exceeds the bounded expansion contract")
                    if member.filename.endswith("/PKG-INFO") or member.filename == "PKG-INFO":
                        if member.file_size > MAX_METADATA_BYTES:
                            raise RuntimeError("source distribution metadata exceeds the bounded size contract")
                        metadata_payloads.append(archive.read(member))
        except BadZipFile as error:
            raise RuntimeError("source distribution is not a valid ZIP archive") from error
    else:
        try:
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
                members = archive.getmembers()
                if not members or len(members) > MAX_SDIST_MEMBERS:
                    raise RuntimeError("source distribution has an invalid member count")
                for member in members:
                    if member.isdir() and not PurePosixPath(member.name).parts:
                        continue
                    if not _safe_archive_member(member.name) or not (member.isdir() or member.isfile()):
                        raise RuntimeError("source distribution contains an unsafe archive member")
                    if member.isfile():
                        total_size += member.size
                        if total_size > MAX_SDIST_UNCOMPRESSED_BYTES:
                            raise RuntimeError("source distribution exceeds the bounded expansion contract")
                    if member.name.endswith("/PKG-INFO") or member.name == "PKG-INFO":
                        if not member.isfile() or member.size > MAX_METADATA_BYTES:
                            raise RuntimeError("source distribution metadata exceeds the bounded size contract")
                        handle = archive.extractfile(member)
                        if handle is None:
                            raise RuntimeError("source distribution metadata could not be read")
                        metadata_payloads.append(handle.read())
        except tarfile.TarError as error:
            raise RuntimeError("source distribution is not a valid tar archive") from error
    if not metadata_payloads:
        raise RuntimeError("source distribution must contain at least one PKG-INFO record")
    for metadata_payload in metadata_payloads:
        metadata = BytesParser().parsebytes(metadata_payload)
        names = metadata.get_all("Name", [])
        versions = metadata.get_all("Version", [])
        if (
            len(names) != 1
            or len(versions) != 1
            or canonical_distribution_name(names[0].strip()) != source.distribution
            or versions[0].strip() != source.version
        ):
            raise RuntimeError("source distribution metadata does not match the approved policy")


def inspect_wheelhouse(wheel_archive: bytes) -> tuple[WheelEvidence, ...]:
    if len(wheel_archive) < 1 or len(wheel_archive) > MAX_WHEELHOUSE_BYTES:
        raise RuntimeError("prefetched verifier wheelhouse exceeds the bounded size contract")
    evidence: list[WheelEvidence] = []
    try:
        with tarfile.open(fileobj=io.BytesIO(wheel_archive), mode="r:") as archive:
            members = archive.getmembers()
            if not members or len(members) > MAX_WHEEL_FILES:
                raise RuntimeError("prefetched verifier wheelhouse has an invalid member count")
            for member in members:
                parts = PurePosixPath(member.name).parts
                if member.isdir() and not parts:
                    continue
                if (
                    not member.isfile()
                    or len(parts) != 1
                    or not _safe_archive_member(member.name)
                    or not member.name.lower().endswith(".whl")
                    or member.size < 1
                    or member.size > MAX_WHEEL_BYTES
                ):
                    raise RuntimeError("prefetched verifier wheelhouse contained an invalid archive member")
                handle = archive.extractfile(member)
                if handle is None:
                    raise RuntimeError("prefetched verifier wheelhouse member could not be read")
                evidence.append(inspect_wheel(parts[0], handle.read()))
    except (tarfile.TarError, OSError) as error:
        raise RuntimeError("prefetched verifier wheelhouse is not a valid tar archive") from error
    if not evidence:
        raise RuntimeError("prefetched verifier wheelhouse archive was empty")
    filenames = [item.filename for item in evidence]
    distributions = [(item.distribution, item.version) for item in evidence]
    if len(filenames) != len(set(filenames)) or len(distributions) != len(set(distributions)):
        raise RuntimeError("prefetched verifier wheelhouse contains duplicate artifacts")
    return tuple(sorted(evidence, key=lambda item: item.filename))


def pack_wheelhouse(wheels: dict[str, bytes]) -> bytes:
    if not wheels or len(wheels) > MAX_WHEEL_FILES:
        raise RuntimeError("source-built verifier wheelhouse has an invalid file count")
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for filename in sorted(wheels):
            payload = wheels[filename]
            _validated_filename(filename, "wheel filename", suffixes=(".whl",))
            if len(payload) < 1 or len(payload) > MAX_WHEEL_BYTES:
                raise RuntimeError("source-built wheel exceeds the bounded size contract")
            member = tarfile.TarInfo(filename)
            member.size = len(payload)
            member.mode = 0o444
            member.uid = member.gid = 0
            member.uname = member.gname = ""
            member.mtime = 0
            archive.addfile(member, io.BytesIO(payload))
    payload = output.getvalue()
    if len(payload) > MAX_WHEELHOUSE_BYTES:
        raise RuntimeError("source-built verifier wheelhouse exceeds the bounded size contract")
    return payload


def validate_policy_wheel_closure(
    entry: SourceWheelPolicyEntry,
    wheels: dict[str, bytes],
) -> tuple[WheelEvidence, ...]:
    expected = {
        filename: (distribution, version, size, sha256)
        for distribution, version, filename, size, sha256 in entry.expected_wheels
    }
    if set(wheels) != set(expected):
        raise RuntimeError("source-built wheel closure does not match the explicit policy allowlist")
    evidence = tuple(
        sorted((inspect_wheel(filename, payload) for filename, payload in wheels.items()), key=lambda x: x.filename)
    )
    for item in evidence:
        distribution, version, size, digest = expected[item.filename]
        if item.distribution != distribution or item.version != version or item.size != size or item.sha256 != digest:
            raise RuntimeError("source-built wheel closure does not match the approved artifact evidence")
    return evidence


def atomic_write_bytes(path: Path, payload: bytes, *, mode: int, replace: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() and not replace:
            raise FileExistsError(path)
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def regular_private_file(path: Path) -> bool:
    try:
        status = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(status.st_mode) and stat.S_IMODE(status.st_mode) in {0o400, 0o600}


def wheel_evidence_dicts(evidence: tuple[WheelEvidence, ...]) -> list[dict[str, object]]:
    return [asdict(item) for item in evidence]
