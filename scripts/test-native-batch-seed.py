#!/usr/bin/env python3
"""Offline native-Save diagnostic guards: real Swift file creation, no Simulator."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "App/TripfolioApp.swift").read_text()
UI = (ROOT / "UITests/BatchImportUITests.swift").read_text()
TOKEN = "12345678-1234-4234-8234-123456789abc"
OWNED = "11111111-1111-4111-8111-111111111111"
spec = importlib.util.spec_from_file_location("native_seed_driver", ROOT / "scripts/test-batch-simulator.py")
driver = importlib.util.module_from_spec(spec); spec.loader.exec_module(driver)


class SeedGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.scratch.cleanup)
        folder = Path(cls.scratch.name)
        helper = APP[APP.index("@MainActor\nprivate enum NativeBatchSeedFiles"):
                     APP.index("@MainActor\nprivate struct NativeBatchSeedView")]
        main = r'''
@main struct Probe {
    @MainActor static func main() {
        let args = Array(CommandLine.arguments.dropFirst())
        if args[0] == "token" {
            print(NativeBatchSeedFiles.token(Array(args.dropFirst())) ?? "rejected")
        } else {
            do {
                let files = try NativeBatchSeedFiles.create(args[1], root: URL(fileURLWithPath: args[2]))
                let values = try files.map { try Data(contentsOf: $0).base64EncodedString() }
                print(String(data: try JSONEncoder().encode(values), encoding: .utf8)!)
            } catch { print("rejected") }
        }
    }
}
'''
        source = folder / "Probe.swift"; cls.binary = folder / "probe"
        source.write_text("import Foundation\nimport Darwin\n" + helper + main)
        subprocess.run(["swiftc", "-swift-version", "6", "-parse-as-library", str(source), "-o", str(cls.binary)],
                       check=True, capture_output=True, text=True, timeout=60)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def probe(self, *args):
        return subprocess.run([str(self.binary), *map(str,args)], check=True,
                              capture_output=True, text=True, timeout=5).stdout.strip()

    def test_real_swift_creates_exact_driver_bytes_in_exclusive_private_folder(self):
        result = json.loads(self.probe("create", TOKEN, self.root))
        expected = [driver.pdf("SYNTHETIC TICKET"), driver.pdf("SYNTHETIC INSURANCE")]
        self.assertEqual([base64.b64decode(item) for item in result], expected)
        folder = self.root / ("TripDocket-NativeSeed-" + TOKEN)
        self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
        for name, data in zip(["synthetic-ticket.pdf","synthetic-insurance.pdf"], expected):
            self.assertEqual((folder/name).read_bytes(), data)
            self.assertEqual((folder/name).stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.probe("create", TOKEN, self.root), "rejected")
        self.assertEqual((folder/"synthetic-ticket.pdf").read_bytes(), expected[0])

    def test_real_swift_rejects_existing_directory_symlink_and_noncanonical_root(self):
        victim = self.root / "victim"; victim.mkdir(); (victim/"keep").write_bytes(b"unchanged")
        owned = self.root / ("TripDocket-NativeSeed-"+TOKEN); owned.symlink_to(victim)
        self.assertEqual(self.probe("create",TOKEN,self.root),"rejected")
        alias = self.root / "alias"; alias.symlink_to(victim)
        self.assertEqual(self.probe("create",TOKEN,alias),"rejected")
        self.assertEqual(list(victim.iterdir()),[victim/"keep"])

    def test_real_swift_token_requires_both_unique_flags_and_canonical_uuid(self):
        args = ["--ui-testing-native-batch-seed","--ui-testing-native-batch-token",TOKEN]
        self.assertEqual(self.probe("token",*args),TOKEN)
        for invalid in [args[1:],args[:1],args+args,args[:-1]+[TOKEN.upper()],
                        args[:-1]+["../outside"],args+["--ui-testing-native-batch-token",TOKEN]]:
            with self.subTest(invalid=invalid):self.assertEqual(self.probe("token",*invalid),"rejected")
        self.assertEqual(self.probe("create","../outside",self.root),"rejected")
        self.assertEqual(list(self.root.iterdir()),[])

    def test_gate_and_ui_keep_explicit_share_and_separate_opt_in_case(self):
        self.assertIn("#if DEBUG && targetEnvironment(simulator)\n// Diagnostic branch fixture",APP)
        self.assertIn("#if DEBUG && targetEnvironment(simulator)\n                if let token",APP)
        view=APP[APP.index("private struct NativeBatchSeedView"):]
        self.assertIn("ExplicitShareSheet(url: selected.url)",view)
        self.assertIn("Button(file.lastPathComponent) { share = SeedShare(url: file) }",view)
        self.assertNotIn("isPro",view);self.assertNotIn("importDocument",view)
        seed=UI[UI.index("func testNativeSaveSeedsBothSyntheticOriginals"):
                UI.index("private func presentRecoverySave")]
        self.assertIn('environment["TRIPDOCKET_NATIVE_SEED_UI"] == "1"',seed)
        self.assertIn('environment["TRIPDOCKET_BATCH_FOLDER"] == "TripDocket-Batch-QA-" + token',seed)
        self.assertIn("executionTimeAllowance = 180",seed)
        self.assertIn("defer { app.terminate() }",seed)
        self.assertEqual(seed.count(".tap()"),3)  # source, share action, exact-folder Save per file
        self.assertIn("recoveryFilesNavigation(folder, picker: picker, app: app)",seed)
        self.assertEqual(driver.CASES,(
            "PlatformTests/testVerifiedPurchaseAndRestoreFromLocalHistory()",
            "BatchImportUITests/testRealFilesBatchRequiresEveryReviewAndPreservesOriginals()"))

    def test_actual_driver_prepare_defers_only_opted_in_destination_writes(self):
        for native in (False,True):
            base=self.root/str(native);base.mkdir()
            run=driver.Driver.__new__(driver.Driver)
            run.args=SimpleNamespace(device=OWNED, native_seed=native)
            run.root=base;run.directory=base/"evidence";run.directory.mkdir()
            run.token=TOKEN;run.folder_name="TripDocket-Batch-QA-"+TOKEN
            run.summary={};run.save=Mock();run.record=Mock();run.source_snapshot=Mock(return_value={})
            project=base/"Tripfolio.xcodeproj";project.mkdir();(project/"project.pbxproj").write_bytes(b"fixture")
            group=base/OWNED/"data/Containers/Shared/AppGroup"/OWNED
            provider=group/"File Provider Storage";provider.mkdir(parents=True)
            inventory={"devices":{"com.apple.CoreSimulator.SimRuntime.iOS-26-2":[
                {"udid":OWNED,"state":"Booted","isAvailable":True,"name":"owned"}]}}
            run.command=Mock(side_effect=[json.dumps(inventory).encode(),f"{driver.GROUP}\t{group}\n".encode()])
            run.prepare()
            self.assertEqual(sorted(p.name for p in run.fixture_directory.iterdir()),
                             [] if native else ["synthetic-insurance.pdf","synthetic-ticket.pdf"])
            for item in run.summary["fixtures"]:
                data=(run.directory/"fixtures"/item["name"]).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(),item["sha256"])
            if native:
                with self.assertRaises((RuntimeError,FileNotFoundError)):run.verify_fixtures()
            else:run.verify_fixtures()


if __name__ == "__main__":
    unittest.main(verbosity=2)
