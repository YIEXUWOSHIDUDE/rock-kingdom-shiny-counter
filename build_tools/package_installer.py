from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import zipfile
from pathlib import Path


FOOTER_MAGIC = b"RKSCZIP1"
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def create_payload(source_directory: Path, destination: Path) -> None:
    source_directory = source_directory.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        destination,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted(
            (item for item in source_directory.rglob("*") if item.is_file()),
            key=lambda item: item.relative_to(source_directory).as_posix(),
        ):
            relative = path.relative_to(source_directory).as_posix()
            info = zipfile.ZipInfo(relative, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            with path.open("rb") as source, archive.open(info, "w") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)


def append_payload(stub: Path, payload: Path, destination: Path) -> None:
    payload_length = payload.stat().st_size
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with temporary.open("wb") as output:
            with stub.open("rb") as source:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            with payload.open("rb") as source:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            output.write(struct.pack("<q", payload_length))
            output.write(FOOTER_MAGIC)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def read_appended_payload(installer: Path) -> bytes:
    with installer.open("rb") as source:
        source.seek(-16, 2)
        payload_length = struct.unpack("<q", source.read(8))[0]
        if source.read(8) != FOOTER_MAGIC:
            raise ValueError("installer footer magic is invalid")
        payload_offset = source.tell() - 16 - payload_length
        if payload_length <= 0 or payload_offset <= 0:
            raise ValueError("installer payload length is invalid")
        source.seek(payload_offset)
        return source.read(payload_length)


def write_directory_manifest(source_directory: Path, destination: Path) -> None:
    source_directory = source_directory.resolve()
    entries = []
    for path in sorted(
        (item for item in source_directory.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(source_directory).as_posix(),
    ):
        if path.resolve() == destination.resolve():
            continue
        entries.append(
            {
                "path": path.relative_to(source_directory).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    destination.write_text(
        json.dumps({"files": entries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def verify_directory_manifest(source_directory: Path, manifest_path: Path) -> None:
    source_directory = source_directory.resolve()
    manifest_path = manifest_path.resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = payload.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("manifest contains no files")
    expected_paths: set[str] = set()
    for entry in entries:
        relative = str(entry["path"]).replace("\\", "/")
        candidate = (source_directory / relative).resolve()
        candidate.relative_to(source_directory)
        if relative in expected_paths:
            raise ValueError(f"duplicate manifest path: {relative}")
        expected_paths.add(relative)
        if not candidate.is_file():
            raise ValueError(f"manifest file is missing: {relative}")
        if candidate.stat().st_size != int(entry["bytes"]):
            raise ValueError(f"manifest size mismatch: {relative}")
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if digest.lower() != str(entry["sha256"]).lower():
            raise ValueError(f"manifest hash mismatch: {relative}")

    actual_paths = {
        path.relative_to(source_directory).as_posix()
        for path in source_directory.rglob("*")
        if path.is_file() and path.resolve() != manifest_path
    }
    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        unexpected = sorted(actual_paths - expected_paths)
        raise ValueError(
            f"manifest file set mismatch; missing={missing}, unexpected={unexpected}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    payload_parser = subparsers.add_parser("payload")
    payload_parser.add_argument("source", type=Path)
    payload_parser.add_argument("destination", type=Path)
    append_parser = subparsers.add_parser("append")
    append_parser.add_argument("stub", type=Path)
    append_parser.add_argument("payload", type=Path)
    append_parser.add_argument("destination", type=Path)
    manifest_parser = subparsers.add_parser("manifest")
    manifest_parser.add_argument("source", type=Path)
    manifest_parser.add_argument("destination", type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("source", type=Path)
    verify_parser.add_argument("manifest", type=Path)
    args = parser.parse_args()

    if args.command == "payload":
        create_payload(args.source, args.destination)
    elif args.command == "append":
        append_payload(args.stub, args.payload, args.destination)
    elif args.command == "manifest":
        write_directory_manifest(args.source, args.destination)
    else:
        verify_directory_manifest(args.source, args.manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
