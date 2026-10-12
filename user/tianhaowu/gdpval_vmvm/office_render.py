from __future__ import annotations

import argparse
import json
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

OFFICE_EXTENSIONS = {".docx", ".pptx", ".xlsx"}
NS0_ROOT_RE = re.compile(r'<ns0:([A-Za-z_][\w.-]*)\b([^>]*?)\bxmlns:ns0="([^"]+)"')
NS0_TAG_RE = re.compile(r"</?ns0:")
NS0_SENTINEL = b'xmlns:ns0="http://schemas.openxmlformats.org/'
UNCLOSED_EXTERNAL_RELATIONSHIP_RE = re.compile(
    r'(<Relationship\b[^<>]*\bTargetMode="External")(?=<Relationship\b|</Relationships>)'
)
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024


def _needs_ooxml_normalization(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if any(
                part in names and NS0_SENTINEL in archive.read(part) for part in ("_rels/.rels", "[Content_Types].xml")
            ):
                return True
            return any(
                UNCLOSED_EXTERNAL_RELATIONSHIP_RE.search(archive.read(part).decode("utf-8"))
                for part in names
                if part.endswith(".rels")
            )
    except (zipfile.BadZipFile, OSError):
        return False


def _normalize_ooxml(source: Path, destination: Path) -> None:
    with (
        zipfile.ZipFile(source) as input_archive,
        zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as output_archive,
    ):
        for member in input_archive.namelist():
            data = input_archive.read(member)
            if member.endswith(".rels") or member == "[Content_Types].xml":
                text = data.decode("utf-8")
                text = NS0_ROOT_RE.sub(r'<\1 xmlns="\3"\2', text)
                text = NS0_TAG_RE.sub(lambda match: match.group(0).replace("ns0:", ""), text)
                if member.endswith(".rels"):
                    text = UNCLOSED_EXTERNAL_RELATIONSHIP_RE.sub(r"\1/>", text)
                data = text.encode("utf-8")
                ElementTree.fromstring(data)
            output_archive.writestr(member, data)


def convert_office_file(path: Path) -> tuple[Path, bool, str]:
    output = path.with_suffix(".pdf")
    if output.is_file():
        return output, True, "already rendered"

    profile = Path(tempfile.mkdtemp(prefix="gdpval-lo-profile-"))
    stage: Path | None = None
    try:
        normalize = _needs_ooxml_normalization(path)
        if normalize or any(character.isspace() for character in path.name):
            stage = Path(tempfile.mkdtemp(prefix="gdpval-lo-stage-"))
            staged_name = re.sub(r"\s+", "_", path.stem) + path.suffix
            input_path = stage / staged_name
            if normalize:
                _normalize_ooxml(path, input_path)
            else:
                shutil.copy2(path, input_path)
            output_dir = stage
        else:
            input_path = path
            output_dir = path.parent

        result = subprocess.run(
            [
                "libreoffice",
                "--headless",
                "--nologo",
                "--nolockcheck",
                "--nodefault",
                "--norestore",
                f"-env:UserInstallation=file://{profile.as_posix()}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_dir),
                str(input_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        staged_output = output_dir / f"{input_path.stem}.pdf"
        if stage is not None and staged_output.is_file():
            shutil.move(staged_output, output)
        if output.is_file():
            return output, True, "rendered"
        detail = (result.stderr or result.stdout).strip()[:500]
        return output, False, f"libreoffice rc={result.returncode}: {detail}"
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        return output, False, f"{type(error).__name__}: {error}"
    finally:
        shutil.rmtree(profile, ignore_errors=True)
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)


def _extract_zip(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    total = 0
    with zipfile.ZipFile(source) as archive:
        for member in archive.infolist():
            total += member.file_size
            if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise ValueError(f"Archive expands beyond {MAX_ARCHIVE_UNCOMPRESSED_BYTES} bytes")
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError(f"Archive contains a symbolic link: {member.filename!r}")
            target = (destination / member.filename).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"Archive path escapes its destination: {member.filename!r}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as input_file, target.open("wb") as output_file:
                shutil.copyfileobj(input_file, output_file)


def _augment_zip(path: Path) -> tuple[bool, list[str]]:
    extracted = Path(tempfile.mkdtemp(prefix="gdpval-zip-render-"))
    try:
        _extract_zip(path, extracted)
        _, errors = preconvert_office(extracted)
        if errors:
            return False, errors
        temporary = path.with_suffix(path.suffix + ".rendered")
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for member in sorted(extracted.rglob("*")):
                if member.is_file():
                    archive.write(member, member.relative_to(extracted).as_posix())
        temporary.replace(path)
        return True, []
    except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        return False, [f"{path.name}: {type(error).__name__}: {error}"]
    finally:
        shutil.rmtree(extracted, ignore_errors=True)


def preconvert_office(root: Path) -> tuple[list[Path], list[str]]:
    rendered: list[Path] = []
    errors: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in OFFICE_EXTENSIONS:
            continue
        output, success, detail = convert_office_file(path)
        if success:
            rendered.append(output)
        else:
            errors.append(f"{path.relative_to(root).as_posix()}: {detail}")
    for path in sorted(root.rglob("*.zip")):
        success, archive_errors = _augment_zip(path)
        if success:
            rendered.append(path)
        else:
            errors.extend(f"{path.relative_to(root).as_posix()}: {error}" for error in archive_errors)
    return rendered, errors


def preconvert_selected(root: Path, relative_paths: list[str]) -> tuple[list[Path], list[str]]:
    rendered: list[Path] = []
    errors: list[str] = []
    seen: set[Path] = set()
    for value in relative_paths:
        relative = PurePosixPath(value)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise ValueError(f"Unsafe selected artifact path: {value!r}")
        path = (root / Path(*relative.parts)).resolve()
        if path != root and root not in path.parents:
            raise ValueError(f"Selected artifact escapes root: {value!r}")
        if path in seen or not path.exists():
            continue
        seen.add(path)
        if path.is_dir():
            selected_rendered, selected_errors = preconvert_office(path)
            rendered.extend(selected_rendered)
            errors.extend(f"{value}: {error}" for error in selected_errors)
        elif path.suffix.lower() in OFFICE_EXTENSIONS:
            output, success, detail = convert_office_file(path)
            if success:
                rendered.append(output)
            else:
                errors.append(f"{value}: {detail}")
        elif path.suffix.lower() == ".zip":
            success, archive_errors = _augment_zip(path)
            if success:
                rendered.append(path)
            else:
                errors.extend(f"{value}: {error}" for error in archive_errors)
    return rendered, errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--selected", action="store_true")
    parser.add_argument("--path", action="append", default=[])
    args = parser.parse_args()
    root = args.root.resolve()
    rendered, errors = preconvert_selected(root, args.path) if args.selected else preconvert_office(root)
    version = subprocess.run(
        ["libreoffice", "--version"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    print(
        json.dumps(
            {
                "rendered": [path.relative_to(root).as_posix() for path in rendered],
                "errors": errors,
                "libreoffice_version": (version.stdout or version.stderr).strip(),
                "python_version": sys.version,
            },
            sort_keys=True,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
