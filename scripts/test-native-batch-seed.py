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
        config = UI[UI.index("    private static func directPreparationToken"):
                    UI.index("    func testNativeCreateOwnedFilesFolder")]
        helper += "\n@MainActor private enum Preparation {\n" + \
            "struct BatchTestFailure: Error { let message: String }\n" + config + \
            "static func check(_ env: [String: String], _ debug: Bool) throws -> String { " + \
            "try directPreparationToken(env, debugSimulator: debug) }\n}\n"
        main = r'''
@main struct Probe {
    @MainActor static func main() {
        let args = Array(CommandLine.arguments.dropFirst())
        if args[0] == "prepare" {
            do {
                let env = try JSONDecoder().decode([String: String].self, from: Data(args[1].utf8))
                print(try Preparation.check(env, args[2] == "true"))
            } catch { print("rejected") }
        } else if args[0] == "token" {
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

    def test_actual_direct_preparation_config_rejects_mixed_modes_and_noncanonical_identity(self):
        env={"TRIPDOCKET_BATCH_PREPARE_UI":"1","TRIPDOCKET_BATCH_PREPARE_TOKEN":TOKEN}
        self.assertEqual(self.probe("prepare",json.dumps(env),"true"),TOKEN)
        rejected=[({},"true"),(env,"false"),({**env,"TRIPDOCKET_BATCH_PREPARE_UI":"0"},"true")]
        rejected += [({**env,"TRIPDOCKET_BATCH_PREPARE_TOKEN":v},"true") for v in ("", "../x", TOKEN.upper())]
        for key in ("TRIPDOCKET_RECOVERY_UI", "TRIPDOCKET_RECOVERY_PHASE", "TRIPDOCKET_RECOVERY_FOLDER",
                    "TRIPDOCKET_NATIVE_SEED_UI", "TRIPDOCKET_NATIVE_SEED_TOKEN",
                    "TRIPDOCKET_NATIVE_FOLDER_UI", "TRIPDOCKET_NATIVE_FOLDER_TOKEN",
                    "TRIPDOCKET_NATIVE_ROOT_UI", "TRIPDOCKET_NATIVE_ROOT_TOKEN",
                    "TRIPDOCKET_BATCH_UI", "TRIPDOCKET_BATCH_FOLDER",
                    "TRIPDOCKET_COMBINED_BATCH_UI", "TRIPDOCKET_BATCH_CHECKPOINT_SESSION"):
            rejected.append(({**env,key:"1"},"true"))
        for value,debug in rejected:
            with self.subTest(value=value,debug=debug):
                self.assertEqual(self.probe("prepare",json.dumps(value),debug),"rejected")

    def test_direct_preparation_opens_only_existing_exporter_and_never_seeds_provider(self):
        case=UI[UI.index("    func testBatchPrepareFilesProviderDirectly"):
                UI.index("    private static func directPreparationToken")]
        self.assertIn('environment["TRIPDOCKET_BATCH_PREPARE_UI"] == "1"',case)
        self.assertIn("executionTimeAllowance = 180",case)
        self.assertIn('let absentFolder = "TripDocket-Batch-Prepare-" + token',case)
        self.assertIn('"--ui-testing-native-batch-token", token',case)
        self.assertEqual(case.count(".tap()"),1)
        self.assertIn("source.element.tap()",case)
        self.assertIn("let picker = try await openNativeFilesRoot(app)",case)
        self.assertIn("isNativeFilesRoot(app)",case)
        self.assertIn('picker.cells.matching(identifier: absentFolder + ", Folder").count == 0',case)
        self.assertIn("saved.count == 0 && !failed.exists",case)
        self.assertIn("defer { app.terminate() }",case)
        self.assertIn("app.state == .notRunning",case)
        for forbidden in ('save.tap()', 'presentRecoverySave(', 'newFolder', 'recordBatchProducer',
                          'typeText(', 'coordinate(', 'createDirectory', 'write(', 'removeItem'):
            self.assertNotIn(forbidden,case)
        self.assertLess(case.index("saved.count == 0"),case.index("app.state == .notRunning"))

    def test_gate_and_ui_keep_explicit_export_and_separate_opt_in_case(self):
        self.assertIn("#if DEBUG && targetEnvironment(simulator)\n// Diagnostic branch fixture",APP)
        self.assertIn("#if DEBUG && targetEnvironment(simulator)\n                if let token",APP)
        view=APP[APP.index("private struct NativeBatchSeedView"):]
        self.assertIn("NativeSeedExportPicker(request: request)",view)
        self.assertIn("Button(file.lastPathComponent) { beginExport(file) }",view)
        self.assertIn("UIDocumentPickerViewController(forExporting: [request.source], asCopy: true)",view)
        self.assertIn('Text("Export verified")',view)
        self.assertIn('"nativeSeed.failure"',view)
        self.assertIn('"nativeSeed.saved." + file.lastPathComponent',view)
        self.assertIn("= AppModel.readExternal",view)
        self.assertIn("try await read(destination, 1024)",view)
        self.assertIn("verified = bytes == expected",view)
        self.assertNotIn("removeItem",view)
        self.assertNotIn("unlink",view)
        self.assertNotIn("isPro",view);self.assertNotIn("importDocument",view)
        seed=UI[UI.index("func testNativeSaveSeedsBothSyntheticOriginals"):
                UI.index("private func presentRecoverySave")]
        self.assertIn('environment["TRIPDOCKET_NATIVE_SEED_UI"] == "1"',seed)
        self.assertIn('environment["TRIPDOCKET_BATCH_FOLDER"] == "TripDocket-Batch-QA-" + token',seed)
        self.assertIn("executionTimeAllowance = 180",seed)
        self.assertIn("defer { app.terminate() }",seed)
        self.assertEqual(seed.count(".tap()"),2)  # source, verified destination Save per file
        self.assertNotIn("saveToFiles",seed)
        self.assertIn('let verified = app.staticTexts["nativeSeed.saved." + filename]',seed)
        self.assertIn('try check(!failed.exists && verified.exists',seed)
        self.assertIn('let nativeRoot = try nativeRootMode("seed")',seed)
        self.assertIn("picker = try await openNativeFilesRoot(app)",seed)
        self.assertIn("isNativeFilesRoot(app)",seed)
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

    def test_actual_driver_native_folder_mode_proves_absence_without_creating_or_adopting(self):
        for existing in (None,"directory","symlink"):
            base=self.root/str(existing);base.mkdir()
            run=driver.Driver.__new__(driver.Driver)
            run.args=SimpleNamespace(device=OWNED,native_seed=True,native_folder=True)
            run.root=base;run.directory=base/"evidence";run.directory.mkdir()
            run.token=TOKEN;run.folder_name="TripDocket-Batch-QA-"+TOKEN
            run.fixture_directory=None;run.fixture_identity=None;run.native_folder_destination=None
            run.summary={};run.save=Mock();run.record=Mock();run.source_snapshot=Mock(return_value={})
            project=base/"Tripfolio.xcodeproj";project.mkdir();(project/"project.pbxproj").write_bytes(b"fixture")
            group=base/OWNED/"data/Containers/Shared/AppGroup"/OWNED
            provider=group/"File Provider Storage";provider.mkdir(parents=True)
            destination=provider/run.folder_name
            if existing=="directory":destination.mkdir();(destination/"keep").write_bytes(b"keep")
            elif existing=="symlink":destination.symlink_to(provider,target_is_directory=True)
            inventory={"devices":{"com.apple.CoreSimulator.SimRuntime.iOS-26-2":[
                {"udid":OWNED,"state":"Booted","isAvailable":True,"name":"owned"}]}}
            run.command=Mock(side_effect=[json.dumps(inventory).encode(),f"{driver.GROUP}\t{group}\n".encode()])
            if existing:
                with self.assertRaisesRegex(RuntimeError,"must not already exist"):run.prepare()
                self.assertTrue(destination.exists())
            else:
                run.prepare()
                self.assertFalse(destination.exists());self.assertEqual(run.native_folder_destination,destination)
                self.assertEqual(len(list((run.directory/"fixtures").iterdir())),2)
                self.assertEqual(run.record.call_args.args[0],"native_folder_absence_verified")
            self.assertIsNone(run.fixture_directory);self.assertIsNone(run.fixture_identity)
            run.remove_fixtures()
            if existing=="directory":self.assertEqual((destination/"keep").read_bytes(),b"keep")
            elif existing=="symlink":self.assertTrue(destination.is_symlink())

    def test_native_folder_case_is_separate_opt_in_one_creation_without_save(self):
        case=UI[UI.index("func testNativeCreateOwnedFilesFolder"):
                UI.index("func testNativeSaveSeedsBothSyntheticOriginals")]
        self.assertIn('environment["TRIPDOCKET_NATIVE_FOLDER_UI"] == "1"',case)
        self.assertIn('environment["TRIPDOCKET_NATIVE_FOLDER_TOKEN"]',case)
        self.assertIn('UUID(uuidString: token)?.uuidString.lowercased() == token',case)
        self.assertIn('environment["TRIPDOCKET_BATCH_FOLDER"] == ownedFolder',case)
        self.assertIn("executionTimeAllowance = 180",case)
        for action in ("more.element.tap()","newFolder.element.tap()",
                       "files.element.coordinate(withNormalizedOffset: current.normalized).tap()"):
            self.assertEqual(case.count(action),1)
        self.assertIn("remainingEditors.count == 0",case)
        self.assertIn("self.isRecoveryFolder(ownedFolder, navigation: navigation.element)",case)
        self.assertIn('app.state == .notRunning',case)
        self.assertNotIn('buttons["Save"]',case)
        self.assertEqual(case.count('coordinate('),1)
        self.assertNotIn("create.element.tap()",case)
        self.assertEqual(case.count("nativeFolderBlankPoint(in: try app.snapshot()"),2)
        self.assertIn("current.point == before.point, current.normalized == before.normalized",case)
        self.assertIn("inlineNames.element.value as? String == ownedFolder",case)
        self.assertNotIn('press(forDuration',case)


class ExportResultGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.scratch.cleanup)
        folder = Path(cls.scratch.name)
        helper = APP[APP.index("@MainActor\n@Observable\nprivate final class NativeSeedExportSession"):
                     APP.index("@MainActor\nprivate struct NativeSeedExportPicker")]
        code = r"""
import Foundation
import Observation

enum ProbeError: Error { case rejected }
enum AppModel {
    static func readExternal(_ url: URL, maximum: Int) async throws -> Data { throw ProbeError.rejected }
}
actor Reader {
    var calls = 0
    var url: URL?
    var maximum = 0
    let mode: String
    init(_ mode: String) { self.mode = mode }
    func read(_ url: URL, _ maximum: Int) async throws -> Data {
        calls += 1; self.url = url; self.maximum = maximum
        await Task.yield()
        if mode == "read-error" { throw ProbeError.rejected }
        if mode == "cancelled-read" { throw CancellationError() }
        if mode == "wrong-bytes" { return Data("incorrect".utf8) }
        return try Data(contentsOf: url)
    }
}
"""
        main = r"""
@main struct Probe {
    @MainActor static func main() async throws {
        let mode = CommandLine.arguments[1]
        let root = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
        let source = root.appendingPathComponent("source/synthetic-ticket.pdf")
        let destination = root.appendingPathComponent("destination/synthetic-ticket.pdf")
        let bytes = Data("known complete source bytes".utf8)
        try FileManager.default.createDirectory(at: source.deletingLastPathComponent(), withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
        try bytes.write(to: source); try bytes.write(to: destination)
        let reader = Reader(mode)
        let expected = mode == "empty-expected" ? Data() : mode == "large-expected" ? Data(repeating: 1,count:1025) : bytes
        let session = NativeSeedExportSession(source: source, expected: expected, read: { url, limit in
            try await reader.read(url,limit)
        })
        var urls = [destination]
        switch mode {
        case "empty": urls = []
        case "multiple": urls = [destination,destination]
        case "wrong-name": urls = [root.appendingPathComponent("destination/another.pdf")]
        case "remote": urls = [URL(string:"https://example.invalid/synthetic-ticket.pdf")!]
        case "foreign-host": urls = [URL(string:"file://foreign.invalid/synthetic-ticket.pdf")!]
        case "source": urls = [source]
        case "source-alias": urls = [source.deletingLastPathComponent().appendingPathComponent("../source/synthetic-ticket.pdf")]
        case "cancel-before": session.cancel()
        default: break
        }
        session.receive(urls)
        if mode == "duplicate" { session.receive([destination]); session.cancel() }
        if mode == "failure-then-valid" { session.receive([destination]) }
        while session.phase == .verifying { await Task.yield() }
        let first = session.phase == .verified
        session.receive([destination]); session.cancel()
        while session.phase == .verifying { await Task.yield() }
        let result:[String:Any] = ["verified":session.phase == .verified,"stable":first == (session.phase == .verified),
            "calls":await reader.calls,"exact_url":await reader.url == destination,"maximum":await reader.maximum,
            "source_unchanged":try Data(contentsOf:source) == bytes,
            "destination_unchanged":try Data(contentsOf:destination) == bytes]
        print(String(data:try JSONSerialization.data(withJSONObject:result,options:[.sortedKeys]),encoding:.utf8)!)
    }
}
"""
        source = folder / "Probe.swift"; cls.binary = folder / "probe"
        source.write_text(code + helper + main)
        subprocess.run(["swiftc", "-swift-version", "6", "-strict-concurrency=complete", "-parse-as-library",
                        str(source), "-o", str(cls.binary)], check=True, capture_output=True, text=True, timeout=60)

    def probe(self, mode):
        with tempfile.TemporaryDirectory() as temp:
            out = subprocess.run([str(self.binary), mode, temp], check=True, capture_output=True, text=True, timeout=5)
            value = json.loads(out.stdout)
            self.assertTrue(value["stable"])
            self.assertTrue(value["source_unchanged"])
            self.assertTrue(value["destination_unchanged"])
            return value

    def test_actual_export_state_requires_single_correct_external_destination_before_read(self):
        for mode in ["empty", "multiple", "wrong-name", "remote", "foreign-host", "source", "source-alias",
                     "empty-expected", "large-expected", "cancel-before"]:
            with self.subTest(mode=mode):
                value = self.probe(mode)
                self.assertFalse(value["verified"]); self.assertEqual(value["calls"],0)

    def test_actual_export_state_requires_complete_bytes_and_preserves_both_files(self):
        for mode in ["success", "read-error", "wrong-bytes", "cancelled-read"]:
            with self.subTest(mode=mode):
                value = self.probe(mode)
                self.assertEqual(value["verified"],mode=="success")
                self.assertEqual(value["calls"],1);self.assertEqual(value["maximum"],1024)
                self.assertTrue(value["exact_url"])

    def test_actual_export_state_rejects_duplicate_and_late_events(self):
        value = self.probe("duplicate")
        self.assertTrue(value["verified"]);self.assertEqual(value["calls"],1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
