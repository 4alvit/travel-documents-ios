#!/usr/bin/env python3
"""Offline verifier tests. Temporary byte fixtures are not rendered PDF evidence."""

import base64
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import uuid

spec = importlib.util.spec_from_file_location("recovery_evidence", Path(__file__).with_name("verify-recovery-evidence.py"))
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


class RecoveryEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="trip-recovery-verifier-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.library_root = self.root / "library"
        self.library_root.mkdir()
        self.folder = self.root / "TripDocket-Recovery-offline-test"
        self.folder.mkdir()
        self.baseline = self.root / "baseline"
        self.original = b"%PDF-synthetic-offline-comparison-fixture-only\n"
        trip, person, sentinel, document = (str(uuid.uuid4()).upper() for _ in range(4))
        self.catalog = {"schemaVersion": 1,
                        "trips": [{"id": trip, "title": "Coast weekend", "departureDate": 817200000}],
                        "travelers": [{"id": person, "name": "Alex Example"}, {"id": sentinel, "name": "Recovery Sentinel"}],
                        "documents": [{"id": document, "tripID": trip, "travelerID": person,
                                       "title": "Weekend reservation", "kind": "booking",
                                       "originalFilename": "sample-reservation.pdf", "storedFilename": document.lower() + ".pdf",
                                       "byteCount": len(self.original), "sha256": evidence.digest(self.original), "importedAt": 816000000.25}]}
        self.current = self.generation()
        self.archive = {"formatVersion": 1, "library": copy.deepcopy(self.catalog),
                        "originals": [{"documentID": document, "data": base64.b64encode(self.original).decode()}]}
        self.write_archive()
        # Prove the offline suite cannot accidentally run a native tool or signal
        # any process if future verifier changes introduce such an operation.
        for target in ("subprocess.Popen", "os.system", "os.kill", "os.killpg"):
            patcher = mock.patch(target, side_effect=AssertionError("No processes in offline verifier tests"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def generation(self, catalog=None, data=None):
        name = str(uuid.uuid4())
        folder = self.library_root / name
        folder.mkdir()
        catalog = self.catalog if catalog is None else catalog
        self.write_json(folder / "catalog.json", catalog)
        (folder / catalog["documents"][0]["storedFilename"]).write_bytes(self.original if data is None else data)
        self.write_json(self.library_root / "active.json", {"formatVersion": 1, "generation": name})
        return folder

    def write_json(self, path, value):
        path.write_bytes(evidence.canonical(value))

    def write_archive(self):
        self.write_json(self.folder / evidence.BACKUP_NAME, self.archive)

    def snapshot(self):
        return evidence.snapshot(self.library_root, self.folder, self.baseline)["manifest_sha256"]

    def compare(self, sha):
        return evidence.compare(self.library_root, self.folder, self.baseline, sha)

    def test_complete_round_trip_and_new_generation(self):
        sha = self.snapshot()
        self.generation()
        result = self.compare(sha)
        self.assertEqual(result["comparison"], "PASS")
        self.assertTrue(result["metadata_equal"] and result["original_bytes_equal"])
        self.assertFalse(result["ui_execution_accepted"] or result["pixel_review_accepted"])

    def test_full_metadata_date_change_is_detected(self):
        sha = self.snapshot()
        changed = copy.deepcopy(self.catalog)
        changed["documents"][0]["importedAt"] += 1
        self.generation(changed)
        with self.assertRaisesRegex(ValueError, "Catalog metadata changed"):
            self.compare(sha)

    def test_missing_unassigned_person_fails_before_reset(self):
        self.archive["library"]["travelers"].pop()
        self.write_archive()
        with self.assertRaisesRegex(ValueError, "fixture count"):
            self.snapshot()
        self.assertFalse(self.baseline.exists())

    def test_wrong_relationship_fails(self):
        self.archive["library"]["documents"][0]["travelerID"] = self.catalog["travelers"][1]["id"]
        self.write_archive()
        with self.assertRaisesRegex(ValueError, "relationship"):
            self.snapshot()

    def test_corrupted_restored_bytes_fail(self):
        sha = self.snapshot()
        self.generation(data=self.original[:-1] + b"X")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.compare(sha)

    def test_same_generation_is_not_restore_evidence(self):
        sha = self.snapshot()
        with self.assertRaisesRegex(ValueError, "new active generation"):
            self.compare(sha)

    def test_duplicate_backup_entry_fails(self):
        self.archive["originals"].append(copy.deepcopy(self.archive["originals"][0]))
        self.write_archive()
        with self.assertRaisesRegex(ValueError, "exactly one original"):
            self.snapshot()

    def test_bad_base64_fails(self):
        self.archive["originals"][0]["data"] = "*" * 10
        self.write_archive()
        with self.assertRaises(ValueError):
            self.snapshot()

    def test_changed_backup_serialization_between_phases_fails(self):
        sha = self.snapshot()
        self.generation()
        with (self.folder / evidence.BACKUP_NAME).open("ab") as stream:
            stream.write(b"\n")
        with self.assertRaisesRegex(ValueError, "backup changed"):
            self.compare(sha)

    def test_baseline_payload_tamper_fails(self):
        sha = self.snapshot()
        self.generation()
        (self.baseline / "original-before.pdf").write_bytes(b"different")
        with self.assertRaisesRegex(ValueError, "Baseline file changed"):
            self.compare(sha)

    def test_baseline_manifest_tamper_fails(self):
        sha = self.snapshot()
        self.generation()
        with (self.baseline / "manifest.json").open("ab") as stream:
            stream.write(b"\n")
        with self.assertRaisesRegex(ValueError, "manifest was changed"):
            self.compare(sha)

    def test_baseline_is_never_overwritten(self):
        self.snapshot()
        with self.assertRaises(FileExistsError):
            self.snapshot()

    def test_active_pointer_not_newest_directory_is_used(self):
        (self.library_root / str(uuid.uuid4())).mkdir()
        self.assertIsNotNone(self.snapshot())

    def test_unsafe_generation_and_filename_are_rejected(self):
        self.write_json(self.library_root / "active.json", {"formatVersion": 1, "generation": "../outside"})
        with self.assertRaises(ValueError):
            self.snapshot()
        self.generation()
        self.archive["library"]["documents"][0]["storedFilename"] = "../outside.pdf"
        self.write_archive()
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            self.snapshot()

    def test_symlink_original_is_not_followed(self):
        target = self.root / "unrelated.pdf"
        target.write_bytes(self.original)
        original = self.current / self.catalog["documents"][0]["storedFilename"]
        original.unlink()
        original.symlink_to(target)
        with self.assertRaises(OSError):
            self.snapshot()

    def test_extra_files_in_destination_fail(self):
        (self.folder / "Documents 2.tripbackup").write_bytes(b"unrelated")
        with self.assertRaisesRegex(ValueError, "only the exact"):
            self.snapshot()

    def test_duplicate_json_key_and_unknown_version_fail(self):
        raw = (self.folder / evidence.BACKUP_NAME).read_bytes()
        (self.folder / evidence.BACKUP_NAME).write_bytes(b'{"formatVersion":1,' + raw[1:])
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            self.snapshot()
        self.archive["formatVersion"] = 2
        self.write_archive()
        with self.assertRaisesRegex(ValueError, "Unsupported backup version"):
            self.snapshot()


if __name__ == "__main__":
    unittest.main(verbosity=2)
