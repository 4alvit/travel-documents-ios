#!/usr/bin/env python3
"""Offline evidence comparison for the paired synthetic recovery UI phases.

Reads only the named stopped app library and owned Files folder. It never
launches processes, creates app data or manufactures an importable fixture.
Passing this comparison alone is NOT acceptance of UI execution or PDF pixels.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

MIB = 1024 * 1024
MAX_BACKUP = 96 * MIB
MAX_CATALOG = 2 * MIB
MAX_ORIGINAL = 16 * MIB
BACKUP_NAME = "Documents.tripbackup"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def directory(path):
    """Require an existing absolute, resolved directory without symlink components.

    The future host supplies resolved paths after checking simulator ownership.
    The app must be stopped; this is not a hostile-concurrent-writer sandbox.
    """
    path = Path(path)
    require(path.is_absolute() and path == path.resolve(strict=True), "Use an absolute resolved directory")
    require(stat.S_ISDIR(path.lstat().st_mode), "Expected a directory")
    return path


def read_file(parent, name, limit):
    require(name not in ("", ".", "..") and Path(name).name == name and "\\" not in name,
            "Unsafe evidence filename")
    fd = os.open(parent / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "Expected a single-link regular file")
        require(0 < before.st_size <= limit, "Evidence file exceeds its size bound or is empty")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        after = os.fstat(fd)
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), "File changed while reading")
        require(len(data) == before.st_size, "Evidence file was truncated or changed")
        return data
    finally:
        os.close(fd)


def decode(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("Non-finite JSON number: " + value)

    return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid_constant)


def valid_uuid(value):
    require(isinstance(value, str), "Expected UUID text")
    parsed = uuid.UUID(value)
    require(value.lower() == str(parsed), "Expected canonical UUID representation")
    return str(parsed)


def fixture(library):
    require(isinstance(library, dict) and set(library) == {"schemaVersion", "trips", "travelers", "documents"},
            "Unexpected library shape")
    require(type(library["schemaVersion"]) is int and library["schemaVersion"] == 1, "Unsupported catalog version")
    for key, count in (("trips", 1), ("travelers", 2), ("documents", 1)):
        require(isinstance(library[key], list) and len(library[key]) == count, "Unexpected fixture count: " + key)
        ids = [valid_uuid(item["id"]) for item in library[key]]
        require(len(set(ids)) == count, "Duplicate fixture identifiers")
    trip = library["trips"][0]
    doc = library["documents"][0]
    require(trip["title"] == "Coast weekend", "Wrong synthetic trip")
    people = {person["name"]: person["id"] for person in library["travelers"]}
    require(set(people) == {"Alex Example", "Recovery Sentinel"}, "Missing assigned or unassigned person")
    require(doc["tripID"] == trip["id"] and doc["travelerID"] == people["Alex Example"], "Wrong fixture relationship")
    require(doc["title"] == "Weekend reservation" and doc["kind"] == "booking", "Wrong document metadata")
    require(doc["originalFilename"] == "sample-reservation.pdf" and doc.get("expiryDate") is None,
            "Unexpected fixture filename or expiry")
    require(doc["storedFilename"] == valid_uuid(doc["id"]) + ".pdf", "Unsafe or unexpected stored filename")
    require(type(doc["byteCount"]) is int and 0 < doc["byteCount"] <= MAX_ORIGINAL, "Invalid original size")
    require(isinstance(doc["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", doc["sha256"]), "Invalid original digest")
    return doc


def verify_original(doc, data):
    require(len(data) == doc["byteCount"] and digest(data) == doc["sha256"], "Original byte count or digest mismatch")


def active_library(root):
    root = directory(root)
    pointer_bytes = read_file(root, "active.json", 4096)
    pointer = decode(pointer_bytes)
    require(set(pointer) == {"formatVersion", "generation"}
            and type(pointer["formatVersion"]) is int and pointer["formatVersion"] == 1, "Unexpected active pointer")
    generation = pointer["generation"]
    require(generation == valid_uuid(generation), "Active generation must be a lowercase UUID")
    current = directory(root / generation)
    catalog_bytes = read_file(current, "catalog.json", MAX_CATALOG)
    library = decode(catalog_bytes)
    doc = fixture(library)
    original = read_file(current, doc["storedFilename"], MAX_ORIGINAL)
    verify_original(doc, original)
    require(read_file(root, "active.json", 4096) == pointer_bytes, "Active generation changed during snapshot")
    return {"pointer": pointer, "pointer_bytes": pointer_bytes, "catalog_bytes": catalog_bytes,
            "library": library, "original": original}


def exported_backup(folder):
    folder = directory(folder)
    require(folder.name.startswith("TripDocket-Recovery-"), "Wrong owned recovery folder name")
    require(sorted(p.name for p in folder.iterdir()) == [BACKUP_NAME], "Expected only the exact UI-exported backup")
    raw = read_file(folder, BACKUP_NAME, MAX_BACKUP)
    archive = decode(raw)
    require(isinstance(archive, dict) and set(archive) == {"formatVersion", "library", "originals"}, "Unexpected archive shape")
    require(type(archive["formatVersion"]) is int and archive["formatVersion"] == 1, "Unsupported backup version")
    doc = fixture(archive["library"])
    items = archive["originals"]
    require(isinstance(items, list) and len(items) == 1, "Expected exactly one original entry")
    entry = items[0]
    require(set(entry) == {"documentID", "data"} and entry["documentID"] == doc["id"], "Wrong or missing backup original ID")
    require(isinstance(entry["data"], str), "Expected base64 original")
    data = base64.b64decode(entry["data"], validate=True)
    verify_original(doc, data)
    return raw, archive["library"], data


def same_library(left, right):
    # Dictionary key order is immaterial. Arrays, all metadata, optional fields,
    # dates, UUID strings and numeric representations must match exactly.
    require(canonical(left) == canonical(right), "Catalog metadata changed")


def snapshot(root, folder, output):
    before = active_library(root)
    raw_backup, library, original = exported_backup(folder)
    same_library(before["library"], library)
    require(before["original"] == original, "Exported original differs from source bytes")
    output = Path(output)
    require(output.is_absolute() and output.name not in ("", ".", ".."), "Use an absolute new evidence directory")
    parent = directory(output.parent)
    require(parent / output.name == output, "Evidence output must be resolved")
    for source in (directory(root), directory(folder)):
        require(not output.is_relative_to(source) and not source.is_relative_to(output), "Evidence output overlaps input")
    output.mkdir()  # Never overwrite a prior baseline, even after partial failure.
    files = {"active-before.json": before["pointer_bytes"], "catalog-before.json": before["catalog_bytes"],
             "original-before.pdf": original, BACKUP_NAME: raw_backup}
    for name, data in files.items():
        with (output / name).open("xb") as stream:
            stream.write(data)
    manifest = {"format": 1, "scope": "offline-synthetic-equality-only",
                "generation_before": before["pointer"]["generation"],
                "files": {name: {"sha256": digest(data), "bytes": len(data)} for name, data in files.items()}}
    encoded = canonical(manifest) + b"\n"
    with (output / "manifest.json").open("xb") as stream:
        stream.write(encoded)
    return {"stage": "snapshot", "comparison": "PASS", "manifest_sha256": digest(encoded),
            "ui_execution_accepted": False, "pixel_review_accepted": False}


def compare(root, folder, baseline, expected_manifest_sha256):
    require(re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256 or ""), "Pin the pre-reset manifest SHA-256")
    baseline = directory(baseline)
    encoded = read_file(baseline, "manifest.json", 16 * 1024)
    require(digest(encoded) == expected_manifest_sha256, "Baseline manifest was changed")
    manifest = decode(encoded)
    require(manifest["format"] == 1 and manifest["scope"] == "offline-synthetic-equality-only", "Unknown baseline format")
    limits = {"active-before.json": 4096, "catalog-before.json": MAX_CATALOG,
              "original-before.pdf": MAX_ORIGINAL, BACKUP_NAME: MAX_BACKUP}
    require(set(manifest["files"]) == set(limits), "Incomplete evidence manifest")
    files = {}
    for name, limit in limits.items():
        data = read_file(baseline, name, limit)
        require(manifest["files"][name] == {"sha256": digest(data), "bytes": len(data)}, "Baseline file changed: " + name)
        files[name] = data
    original_catalog = decode(files["catalog-before.json"])
    fixture(original_catalog)
    after = active_library(root)
    raw_backup, library, original = exported_backup(folder)
    require(raw_backup == files[BACKUP_NAME], "The UI-exported backup changed between phases")
    same_library(original_catalog, library)
    same_library(original_catalog, after["library"])
    require(after["original"] == files["original-before.pdf"] == original, "Restored original bytes changed")
    require(after["pointer"]["generation"] != manifest["generation_before"], "Restore must publish a new active generation")
    return {"stage": "compare", "comparison": "PASS", "metadata_equal": True, "original_bytes_equal": True,
            "backup_unchanged": True, "new_active_generation": True, "trips": 1, "people": 2, "documents": 1,
            "manifest_sha256": expected_manifest_sha256, "ui_execution_accepted": False, "pixel_review_accepted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    first = commands.add_parser("snapshot")
    second = commands.add_parser("compare")
    for command in (first, second):
        command.add_argument("--library-root", required=True, type=Path)
        command.add_argument("--files-folder", required=True, type=Path)
    first.add_argument("--output", required=True, type=Path)
    second.add_argument("--baseline", required=True, type=Path)
    second.add_argument("--expected-manifest-sha256", required=True)
    args = parser.parse_args()
    try:
        if args.command == "snapshot":
            result = snapshot(args.library_root, args.files_folder, args.output)
        else:
            result = compare(args.library_root, args.files_folder, args.baseline, args.expected_manifest_sha256)
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        parser.exit(1, "Evidence comparison failed: " + str(error) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
