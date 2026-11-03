#!/usr/bin/env python3
"""Capture native-created-folder import evidence without granting release acceptance."""
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import sys

HERE = Path(__file__).resolve().parent
PROVIDER_SHA256 = "e2f0c132548242b520fb6665c5fcc9e70e44062e9db0798729b65879a5b44047"


def verify_provider():
    path = HERE / "diagnose-batch-provider.py"
    metadata = path.lstat()
    if (not stat.S_ISREG(metadata.st_mode) or path.resolve() != path
            or metadata.st_size > 2 * 1024**2
            or hashlib.sha256(path.read_bytes()).hexdigest() != PROVIDER_SHA256):
        raise RuntimeError("Native-folder diagnostic provider helper changed")


verify_provider()
spec = importlib.util.spec_from_file_location("folder_diagnostic_provider", HERE / "diagnose-batch-provider.py")
provider = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider)
verify_provider()
q = provider.q


class FolderQualification(provider.ProviderLogQualification):
    native_folder_control = True
    diagnostic_scope = "Persisted logs for native-created-folder control; mandatory preparation and combined seed/main retained"

    def __init__(self, root, mode, env):
        q.require(mode == "batch" and env.get("QUALIFICATION_NATIVE_FOLDER_CONTROL") == "1",
                  "Select the explicit native-created-folder batch control")
        super().__init__(root, mode, env)

    def save(self):
        self.report.setdefault("diagnostic_native_folder", {
            "enabled": True, "release_acceptance": False,
            "scope": "Native-created subfolder; additional folder case plus unchanged mandatory preparation/seed/main cases",
            "folder_creation": "Files UI only; host verifies absent-before and exact empty leaf after",
            "expected_phase_case_counts": [2, 1, 2], "expected_result_bundles": 3,
            "provider_sha256": PROVIDER_SHA256,
        })
        super().save()


def main():
    q.require(sys.argv[1:] == ["--mode", "batch"], "Native-folder diagnostic requires --mode batch")
    q.require(os.environ.get("QUALIFICATION_NATIVE_FOLDER_CONTROL") == "1",
              "Select the explicit native-created-folder batch control")
    verify_provider()
    provider.verify_pins(HERE)
    previous = q.Qualification
    q.require(previous is provider.BaseQualification, "Native-folder diagnostic inherited class changed")
    q.Qualification = FolderQualification
    try:
        return q.main()
    finally:
        q.Qualification = previous


if __name__ == "__main__":
    sys.exit(main())
