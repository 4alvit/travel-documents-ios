#!/usr/bin/env python3
"""Exercise both real driver inventory boundaries without invoking native tools."""
import importlib.util
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


HERE = Path(__file__).resolve().parent
UUID = "12345678-1234-1234-1234-123456789ABC"
OTHER_UUID = "87654321-4321-4321-4321-CBA987654321"
IOS = "com.apple.CoreSimulator.SimRuntime.iOS-26-2"
TVOS = "com.apple.CoreSimulator.SimRuntime.tvOS-26-2"


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DRIVERS = {kind: load("test-" + kind + "-simulator") for kind in ("privacy", "batch")}


class InventoryAccepted(Exception):
    """Stop before the first enrollment read or Files container lookup."""


def device(**changes):
    return {"udid": UUID, "isAvailable": True, "state": "Booted",
            "name": "Owned test device", **changes}


class InventoryTests(unittest.TestCase):
    def check_inventory(self, inventory, accepted=False, error="available.*booted iOS simulator"):
        for kind, module in DRIVERS.items():
            with self.subTest(driver=kind), TemporaryDirectory() as directory:
                root = Path(directory)
                project = root / "Tripfolio.xcodeproj"
                project.mkdir()
                (project / "project.pbxproj").touch()
                # Avoid the constructor's repository output creation while
                # exercising the production prepare() and command() methods.
                driver = module.Driver.__new__(module.Driver)
                driver.args = SimpleNamespace(device=UUID)
                driver.root = root
                driver.summary = {}
                driver.record = Mock()
                driver.write_summary = Mock()
                driver.save = Mock()
                driver.remaining = Mock(return_value=1200)
                driver.source_snapshot = Mock(return_value={"synthetic": True})
                calls = []
                boundary = (["xcrun", "simctl", "notify_get_state", UUID, module.ENROLLMENT]
                            if kind == "privacy" else
                            ["xcrun", "simctl", "get_app_container", UUID,
                             "com.apple.DocumentsApp", "groups"])

                def run(argv, **kwargs):
                    calls.append(list(argv))
                    self.assertEqual(kwargs["cwd"], root)
                    self.assertEqual(kwargs["timeout"], 30)
                    self.assertIs(kwargs["check"], False)
                    if len(calls) == 1:
                        self.assertEqual(list(argv), ["xcrun", "simctl", "list", "devices", "--json"])
                        payload = json.dumps({"devices": inventory})
                        if not kwargs.get("text"):
                            payload = payload.encode()
                        return subprocess.CompletedProcess(argv, 0, payload,
                                                           "" if kwargs.get("text") else b"")
                    self.assertEqual(len(calls), 2)
                    self.assertEqual(list(argv), boundary)
                    raise InventoryAccepted()

                with patch.object(module.subprocess, "run", side_effect=run), \
                     patch.object(module.subprocess, "Popen", side_effect=AssertionError("Native spawn forbidden")), \
                     patch.object(module, "source_provenance", return_value={"synthetic": True}, create=True):
                    if accepted:
                        with self.assertRaises(InventoryAccepted):
                            driver.prepare()
                        self.assertEqual(calls[-1], boundary)
                        self.assertEqual(len(calls), 2)
                        self.assertEqual(driver.summary["runtime"], IOS)
                        self.assertEqual(driver.summary["device_name"], "Owned test device")
                    else:
                        with self.assertRaisesRegex(RuntimeError, error):
                            driver.prepare()
                        self.assertEqual(len(calls), 1)
                        self.assertNotIn("runtime", driver.summary)
                        driver.source_snapshot.assert_not_called()

    def test_exact_owned_device_is_accepted(self):
        self.check_inventory({IOS: [device()]}, accepted=True)

    def test_owned_device_with_unrelated_unavailable_entries_is_accepted(self):
        self.check_inventory({IOS: [device(udid=OTHER_UUID, isAvailable=False, state="Shutdown"),
                                    device(udid=UUID.lower())],
                              TVOS: [device(udid=OTHER_UUID, isAvailable=False)]}, accepted=True)

    def test_missing_owned_device_is_rejected(self):
        self.check_inventory({IOS: [device(udid=OTHER_UUID)]}, error="one available simulator")

    def test_duplicate_owned_device_is_rejected(self):
        self.check_inventory({IOS: [device(), device()]}, error="one available simulator")

    def test_duplicate_across_runtimes_is_rejected(self):
        self.check_inventory({IOS: [device()], TVOS: [device()]}, error="one available simulator")

    def test_unavailable_duplicate_is_not_hidden_by_filtering(self):
        self.check_inventory({IOS: [device(), device(isAvailable=False)]}, error="one available simulator")

    def test_unavailable_owned_device_is_rejected(self):
        self.check_inventory({IOS: [device(isAvailable=False)]})

    def test_missing_availability_is_rejected(self):
        owned = device()
        del owned["isAvailable"]
        self.check_inventory({IOS: [owned]})

    def test_non_ios_device_is_rejected(self):
        self.check_inventory({TVOS: [device()]})

    def test_shutdown_device_is_rejected(self):
        self.check_inventory({IOS: [device(state="Shutdown")]})


if __name__ == "__main__":
    unittest.main()
