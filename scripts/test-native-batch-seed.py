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
                    UI.index("    private func acknowledgeNativeFolderKeyboardIntroduction(")]
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
        self.assertIn("let picker = try await openNativeFilesRoot(app, initialTimeout: .seconds(30))",case)
        self.assertEqual(UI.count("initialTimeout: .seconds(30)"),1)
        self.assertIn("initialTimeout: Duration = .seconds(15)",UI)
        route=UI[UI.index("    private func openNativeFilesRoot"):
                 UI.index("    private func openLocalFilesFolder")]
        self.assertEqual(route.count("timeout: initialTimeout"),1)
        self.assertNotIn("timeout:",route[route.index("        if !browserReady()"):])
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
        self.assertIn("UIDocumentPickerViewController(forExporting: request.sources, asCopy: true)",view)
        self.assertIn('Button("Export both synthetic PDFs") { beginExportBoth() }',view)
        self.assertIn('.accessibilityIdentifier("nativeSeed.exportBoth")',view)
        self.assertIn('for name in names { exports[name] = request }',view)
        self.assertIn('guard !reopenEnabled, !unavailable, !pending',view)
        self.assertIn('Text("Returned destination verified")',view)
        self.assertIn('request.verifiedNames.contains(file.lastPathComponent)',view)
        self.assertIn('exports[$0.0]?.verifiedNames.contains($0.0) == true',view)
        self.assertIn('.accessibilityIdentifier("nativeSeed.callbackVerified")',view)
        self.assertIn('.accessibilityValue(callbackVerification)',view)
        self.assertIn('"nativeSeed.failure"',view)
        self.assertIn('"nativeSeed.saved." + file.lastPathComponent',view)
        self.assertIn("= AppModel.readExternal",view)
        self.assertIn("try await read(destination, 1024)",view)
        self.assertIn("guard bytes == expected[destination.lastPathComponent]",view)
        self.assertNotIn("removeItem",view)
        self.assertNotIn("unlink",view)
        self.assertNotIn("isPro",view);self.assertNotIn("importDocument",view)
        seed=UI[UI.index("func testNativeSaveSeedsBothSyntheticOriginals"):
                UI.index("private func presentRecoverySave")]
        self.assertIn('environment["TRIPDOCKET_NATIVE_SEED_UI"] == "1"',seed)
        self.assertIn('environment["TRIPDOCKET_BATCH_FOLDER"] == "TripDocket-Batch-QA-" + token',seed)
        self.assertIn("executionTimeAllowance = 180",seed)
        self.assertIn("defer { app.terminate() }",seed)
        ordinary, control = seed.rsplit('        if reopenControl {', 1)
        control, completion = control.split('        // Host compares both exact destination bytes;', 1)
        self.assertEqual((ordinary + completion).count(".tap()"),2)  # source, verified Save per export group
        self.assertIn('let exportGroups = [filenames]',ordinary)
        self.assertIn('let sourceIdentifier = "nativeSeed.exportBoth"',ordinary)
        self.assertEqual(control.count(".tap()"),1)
        self.assertIn('reopen.tap()',control)
        self.assertIn('let reopenControl = reopenValue == "1"',ordinary)
        self.assertIn('guard reopenValue == nil || reopenValue == "" || reopenValue == "1"',ordinary)
        self.assertIn('guard !reopenControl || (nativeRoot && checkpoint != nil)',ordinary)
        self.assertIn('failed: failed, observeLateFailure: reopenControl)',ordinary)
        launch, conditional = ordinary.split('        if reopenControl {\n',1)
        self.assertIn('"--ui-testing-batch-diagnostics"',launch)
        self.assertIn('app.launchArguments += ["--ui-testing-native-reopen"]',conditional)
        self.assertIn('try await selectRealFiles(app, nativeRoot: true, observeLateFailure: false)',control)
        self.assertIn('try check(verified.exists && !failed.exists',control)
        self.assertNotIn('app.launch()',control)
        self.assertNotIn('app.terminate()',control)
        self.assertNotIn("saveToFiles",seed)
        self.assertIn('let verified = [app.staticTexts["nativeSeed.callbackVerified"]]',seed)
        self.assertIn('try check(expectedValues.contains(callbackValue)',seed)
        self.assertLess(seed.index('expectedValues.contains(callbackValue)'), seed.index('Self.recordBatchProducer(checkpoint)'))
        self.assertIn('try check(!failed.exists && verified.allSatisfy { $0.exists }',seed)
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
        configuration=UI[UI.index("private static func nativeFolderConfiguration"):
                         UI.index("func testNativeCreateOwnedFilesFolder")]
        self.assertIn('environment["TRIPDOCKET_NATIVE_FOLDER_UI"] == "1"',case)
        self.assertIn('Self.nativeFolderConfiguration(environment, debugSimulator: debugSimulator)',case)
        self.assertIn('environment["TRIPDOCKET_NATIVE_FOLDER_TOKEN"]',configuration)
        self.assertIn('UUID(uuidString: token)?.uuidString.lowercased() == token',configuration)
        self.assertIn('environment["TRIPDOCKET_BATCH_FOLDER"] == "TripDocket-Batch-QA-" + token',configuration)
        self.assertIn("executionTimeAllowance = 180",case)
        for action in ("more.element.tap()","newFolder.element.tap()",
                       "files.element.coordinate(withNormalizedOffset: current.normalized).tap()"):
            self.assertEqual(case.count(action),1)
        handoff=case[case.index("files.element.coordinate(withNormalizedOffset: current.normalized).tap()")+len("files.element.coordinate(withNormalizedOffset: current.normalized).tap()") :]
        self.assertNotIn("remainingEditors",handoff)
        self.assertNotIn("directory.element.tap()",handoff)
        self.assertIn('capture(app, "Native folder rename requested; host empty-folder verification pending")',handoff)
        self.assertLess(handoff.index("saved.count == 0 && !failed.exists"),handoff.index("app.terminate()"))
        self.assertLess(handoff.index("app.terminate()"),handoff.index("app.state == .notRunning"))
        self.assertIn('app.state == .notRunning',case)
        self.assertNotIn('buttons["Save"]',case)
        self.assertEqual(case.count('coordinate('),1)
        self.assertNotIn("create.element.tap()",case)
        self.assertEqual(case.count("nativeFolderBlankPoint(in:"),2)
        for name in ("beforeBlankSnapshots", "currentBlankSnapshots"):
            self.assertIn(name + " = try nativeFolderSnapshots(app)",case)
            self.assertIn("in: " + name + ".picker",case)
            self.assertIn("applicationSnapshot: " + name + ".application",case)
        self.assertIn("current.point == before.point, current.normalized == before.normalized",case)
        self.assertIn("inlineNames.element.value as? String == ownedFolder",case)
        self.assertEqual(case.count('press(forDuration'),1)
        self.assertIn('created.element.press(forDuration: 1)',case)
        self.assertIn('Self.nativeFolderRenameFrame(in: snapshots.picker,',case)
        self.assertIn('applicationSnapshot: snapshots.application,',case)
        self.assertIn('localTitle: localTitle) == before',case)
        self.assertIn('created.count == 1 && created.element.frame == before',case)
        self.assertIn('rename.count == 1 && rename.element.isEnabled && rename.element.isHittable',case)


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
    var urls: [URL] = []
    var maximum = 0
    var pending: CheckedContinuation<Data, any Error>?
    let mode: String
    init(_ mode: String) { self.mode = mode }
    func read(_ url: URL, _ maximum: Int) async throws -> Data {
        calls += 1; self.url = url; self.maximum = maximum; urls.append(url)
        if calls == 2 && mode.hasPrefix("array-held") {
            return try await withCheckedThrowingContinuation { pending = $0 }
        }
        await Task.yield()
        if mode == "read-error" || mode == "array-partial-error" { throw ProbeError.rejected }
        if mode == "read-error-known" {
            throw NSError(domain: NSCocoaErrorDomain, code: 257,
                          userInfo: [NSLocalizedDescriptionKey: "private description", NSFilePathErrorKey: "/private/secret.pdf"])
        }
        if mode == "read-error-unknown" {
            throw NSError(domain: "/private/secret-domain", code: 93,
                          userInfo: [NSLocalizedDescriptionKey: "private description"])
        }
        if mode == "cancelled-read" { throw CancellationError() }
        if mode == "wrong-bytes" || mode == "array-partial-wrong" { return Data("incorrect".utf8) }
        if calls == 2 && mode == "array-wrong-second" { return Data("incorrect".utf8) }
        if calls == 2 && mode == "array-error-second" { throw ProbeError.rejected }
        return try Data(contentsOf: url)
    }
    func release(_ data: Data) { let saved = pending; pending = nil; saved?.resume(returning: data) }
    var isHeld: Bool { pending != nil }
}
"""
        main = r"""
@main struct Probe {
    @MainActor static func main() async throws {
        let mode = CommandLine.arguments[1]
        let root = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
        let source = root.appendingPathComponent("source/synthetic-ticket.pdf")
        let destination = root.appendingPathComponent("destination/synthetic-ticket.pdf")
        let secondSource = root.appendingPathComponent("source/synthetic-insurance.pdf")
        let secondDestination = root.appendingPathComponent("destination/synthetic-insurance.pdf")
        let bytes = Data("known complete source bytes".utf8)
        let secondBytes = Data("different complete second source bytes".utf8)
        try FileManager.default.createDirectory(at: source.deletingLastPathComponent(), withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
        try bytes.write(to: source); try bytes.write(to: destination)
        try secondBytes.write(to: secondSource); try secondBytes.write(to: secondDestination)
        let reader = Reader(mode)
        let expected = mode == "empty-expected" ? Data() : mode == "large-expected" ? Data(repeating: 1,count:1025) : bytes
        let array = mode.hasPrefix("array-")
        let session: NativeSeedExportSession
        if array {
            var sources = [source,secondSource]
            var expected = [source.lastPathComponent: bytes,secondSource.lastPathComponent: secondBytes]
            switch mode {
            case "array-no-sources": sources = []; expected = [:]
            case "array-too-many-sources":
                sources.append(root.appendingPathComponent("source/third.pdf")); expected["third.pdf"] = bytes
            case "array-duplicate-sources": sources = [source,source]
            case "array-wrong-source-name": sources[1] = root.appendingPathComponent("source/other.pdf")
            case "array-missing-expected": expected.removeValue(forKey: secondSource.lastPathComponent)
            case "array-empty-expected": expected[secondSource.lastPathComponent] = Data()
            case "array-large-expected": expected[secondSource.lastPathComponent] = Data(repeating: 1,count:1025)
            default: break
            }
            session = NativeSeedExportSession(sources: sources, expected: expected,
                read: { try await reader.read($0,$1) })
        } else {
            session = NativeSeedExportSession(source: source, expected: expected, read: { url, limit in
                try await reader.read(url,limit)
            })
        }
        var urls = array ? [destination,secondDestination] : [destination]
        switch mode {
        case "empty": urls = []
        case "multiple": urls = [destination,destination]
        case "wrong-name": urls = [root.appendingPathComponent("destination/another.pdf")]
        case "private-name": urls = [root.appendingPathComponent("destination/private-secret-name.pdf")]
        case "directory-result": urls = [destination.deletingLastPathComponent()]
        case "remote": urls = [URL(string:"https://example.invalid/synthetic-ticket.pdf")!]
        case "foreign-host": urls = [URL(string:"file://foreign.invalid/synthetic-ticket.pdf")!]
        case "source": urls = [source]
        case "source-alias": urls = [source.deletingLastPathComponent().appendingPathComponent("../source/synthetic-ticket.pdf")]
        case "cancel-before": session.cancel()
        case "array-reverse": urls.reverse()
        case "array-partial-insurance", "array-partial-error", "array-partial-wrong",
             "array-partial-then-aggregate": urls = [secondDestination]
        case "array-partial-ticket": urls = [destination]
        case "array-empty", "array-failed-then-valid": urls = []
        case "array-duplicate": urls = [destination,destination]
        case "array-duplicate-name": urls = [destination,root.appendingPathComponent("other/synthetic-ticket.pdf")]
        case "array-extra": urls.append(root.appendingPathComponent("destination/extra.pdf"))
        case "array-source": urls[1] = secondSource
        case "array-source-alias": urls[1] = secondSource.deletingLastPathComponent().appendingPathComponent("../source/synthetic-insurance.pdf")
        case "array-remote": urls[1] = URL(string:"https://example.invalid/synthetic-insurance.pdf")!
        case "array-foreign-host": urls[1] = URL(string:"file://foreign.invalid/synthetic-insurance.pdf")!
        case "array-wrong-name": urls[1] = root.appendingPathComponent("destination/other.pdf")
        case "array-cancel-before": session.cancel()
        default: break
        }
        session.receive(urls)
        if mode == "array-observation-cap" {
            for _ in 0..<80 { session.receive([]); session.cancel() }
        }
        if mode == "duplicate" { session.receive([destination]); session.cancel() }
        if mode == "failure-then-valid" { session.receive([destination]) }
        if mode == "array-failed-then-valid" { session.receive([destination,secondDestination]) }
        if mode == "array-partial-then-aggregate" { session.receive([destination,secondDestination]); session.cancel() }
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .seconds(3))
        var heldWithoutSuccess = false
        if mode.hasPrefix("array-held") {
            while !(await reader.isHeld) {
                guard clock.now < deadline else { throw ProbeError.rejected }
                try await Task.sleep(for: .milliseconds(1))
            }
            heldWithoutSuccess = session.phase == .verifying && session.verifiedNames.isEmpty
                && session.callbackVerification == nil
            guard heldWithoutSuccess else { throw ProbeError.rejected }
            // An accepted delegate result owns verification; later events
            // cannot replace it or publish success before the second read.
            session.receive([]); session.receive([destination,secondDestination]); session.cancel()
            await reader.release(mode == "array-held-wrong" ? Data("wrong".utf8) : secondBytes)
        }
        while session.phase == .verifying {
            guard clock.now < deadline else { throw ProbeError.rejected }
            try await Task.sleep(for: .milliseconds(1))
        }
        let first = session.phase == .verified
        let firstNames = session.verifiedNames
        let firstEvidence = session.callbackVerification
        session.receive(array ? [destination,secondDestination] : [destination]); session.cancel()
        while session.phase == .verifying {
            guard clock.now < deadline else { throw ProbeError.rejected }
            try await Task.sleep(for: .milliseconds(1))
        }
        let readURLs = await reader.urls
        let result:[String:Any] = ["verified":session.phase == .verified,
            "stable":first == (session.phase == .verified) && firstNames == session.verifiedNames
                && firstEvidence == session.callbackVerification,
            "verified_names":session.verifiedNames,"callback_evidence":session.callbackVerification as Any? ?? NSNull(),
            "calls":await reader.calls,"exact_url":await reader.url == destination,"maximum":await reader.maximum,
            "exact_urls":readURLs == Array(urls.prefix(readURLs.count)),
            "read_names":readURLs.map(\.lastPathComponent),"held_without_success":heldWithoutSuccess,
            "pending_drained": !(await reader.isHeld),
            "source_unchanged":try Data(contentsOf:source) == bytes,
            "destination_unchanged":try Data(contentsOf:destination) == bytes,
            "second_source_unchanged":try Data(contentsOf:secondSource) == secondBytes,
            "second_destination_unchanged":try Data(contentsOf:secondDestination) == secondBytes]
        print(String(data:try JSONSerialization.data(withJSONObject:result,options:[.sortedKeys]),encoding:.utf8)!)
    }
}
"""
        source = folder / "Probe.swift"; cls.binary = folder / "probe"
        source.write_text(code + helper + main)
        subprocess.run(["swiftc", "-swift-version", "6", "-strict-concurrency=complete", "-parse-as-library",
                        str(source), "-o", str(cls.binary)], check=True, capture_output=True, text=True, timeout=60)

    def probe(self, mode, diagnostics=None):
        with tempfile.TemporaryDirectory() as temp:
            arguments = [str(self.binary), mode, temp]
            if diagnostics is not None:
                arguments.append(diagnostics)
            out = subprocess.run(arguments, check=True, capture_output=True, text=True, timeout=5)
            lines = out.stdout.splitlines()
            self.last_trace = lines[:-1]
            self.assertTrue(all(line.startswith("NATIVE_SEED_EXPORT ") for line in self.last_trace))
            self.assertEqual(out.stderr, "")
            value = json.loads(lines[-1])
            self.assertTrue(value["stable"])
            self.assertTrue(value["source_unchanged"])
            self.assertTrue(value["destination_unchanged"])
            self.assertTrue(value["second_source_unchanged"])
            self.assertTrue(value["second_destination_unchanged"])
            self.assertTrue(value["pending_drained"])
            if not value["verified"]:
                self.assertEqual(value["verified_names"], [])
                self.assertIsNone(value["callback_evidence"])
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

    def test_actual_array_export_matches_names_without_destination_order_assumption(self):
        for mode,names in [("array-success",["synthetic-ticket.pdf","synthetic-insurance.pdf"]),
                           ("array-reverse",["synthetic-insurance.pdf","synthetic-ticket.pdf"])]:
            with self.subTest(mode=mode):
                value = self.probe(mode)
                self.assertTrue(value["verified"]);self.assertEqual(value["calls"],2)
                self.assertEqual(value["read_names"],names);self.assertTrue(value["exact_urls"])
                self.assertEqual(value["maximum"],1024)
                self.assertEqual(value["verified_names"],sorted(names))
                self.assertEqual(value["callback_evidence"],
                    "sourceCount=2 sourceNames=synthetic-insurance.pdf,synthetic-ticket.pdf "
                    "verifiedCount=2 verifiedNames=synthetic-insurance.pdf,synthetic-ticket.pdf")

    def test_actual_array_export_reports_only_returned_verified_destinations(self):
        for mode,name in [("array-partial-insurance","synthetic-insurance.pdf"),
                          ("array-partial-ticket","synthetic-ticket.pdf"),
                          ("array-partial-then-aggregate","synthetic-insurance.pdf")]:
            with self.subTest(mode=mode):
                value = self.probe(mode)
                self.assertTrue(value["verified"]); self.assertEqual(value["calls"],1)
                self.assertEqual(value["read_names"],[name]); self.assertTrue(value["exact_urls"])
                self.assertEqual(value["verified_names"],[name])
                self.assertEqual(value["callback_evidence"],
                    "sourceCount=2 sourceNames=synthetic-insurance.pdf,synthetic-ticket.pdf "
                    "verifiedCount=1 verifiedNames=" + name)

    def test_actual_array_export_rejects_invalid_whole_callback_before_any_read(self):
        for mode in ["array-empty","array-duplicate","array-duplicate-name","array-extra","array-source",
                     "array-source-alias","array-remote","array-foreign-host",
                     "array-wrong-name","array-cancel-before","array-failed-then-valid"]:
            with self.subTest(mode=mode):
                value = self.probe(mode)
                self.assertFalse(value["verified"]);self.assertEqual(value["calls"],0)

    def test_actual_array_export_preserves_complete_source_validation(self):
        for mode in ["array-no-sources","array-too-many-sources","array-duplicate-sources",
                     "array-wrong-source-name","array-missing-expected","array-empty-expected",
                     "array-large-expected"]:
            with self.subTest(mode=mode):
                value = self.probe(mode)
                self.assertFalse(value["verified"]); self.assertEqual(value["calls"],0)

    def test_actual_partial_callback_still_requires_complete_correct_bytes(self):
        for mode in ["array-partial-error","array-partial-wrong"]:
            with self.subTest(mode=mode):
                value = self.probe(mode)
                self.assertFalse(value["verified"]); self.assertEqual(value["calls"],1)
                self.assertTrue(value["exact_urls"])

    def test_actual_array_export_waits_for_second_read_and_rejects_late_replacement(self):
        for mode in ["array-held-success","array-held-wrong","array-wrong-second","array-error-second"]:
            with self.subTest(mode=mode):
                value = self.probe(mode)
                self.assertEqual(value["verified"],mode=="array-held-success")
                self.assertEqual(value["calls"],2);self.assertTrue(value["exact_urls"])
                if mode.startswith("array-held"):
                    self.assertTrue(value["held_without_success"])

    def test_export_trace_requires_exact_flag_and_stays_in_debug_simulator_fixture(self):
        for flag in (None, "--ui-testing-batch-diagnostics-extra", "ui-testing-batch-diagnostics"):
            self.assertTrue(self.probe("array-success", diagnostics=flag)["verified"])
            self.assertEqual(self.last_trace, [])
        self.assertTrue(self.probe("array-success", diagnostics="--ui-testing-batch-diagnostics")["verified"])
        self.assertTrue(self.last_trace)
        conditional = APP[APP.index("#if DEBUG && targetEnvironment(simulator)\n// Diagnostic branch fixture"):]
        self.assertIn("NATIVE_SEED_EXPORT", conditional)
        self.assertNotIn("NATIVE_SEED_EXPORT", APP[:APP.index(conditional)])
        self.assertTrue(conditional.rstrip().endswith("#endif"))

    def test_export_trace_preserves_actual_outcomes_reads_and_late_event_behavior(self):
        modes = ["success", "read-error", "wrong-bytes", "cancelled-read", "empty", "multiple",
                 "wrong-name", "remote", "foreign-host", "source", "source-alias", "empty-expected",
                 "large-expected", "cancel-before", "duplicate", "array-success", "array-reverse",
                 "array-partial-insurance", "array-partial-ticket", "array-partial-then-aggregate",
                 "array-partial-error", "array-partial-wrong", "array-empty",
                 "array-duplicate", "array-duplicate-name", "array-extra", "array-source", "array-wrong-name",
                 "array-cancel-before", "array-failed-then-valid", "array-held-success",
                 "array-held-wrong", "array-wrong-second", "array-error-second"]
        for mode in modes:
            with self.subTest(mode=mode):
                quiet = self.probe(mode)
                observed = self.probe(mode, diagnostics="--ui-testing-batch-diagnostics")
                self.assertEqual(observed, quiet)
                self.assertLessEqual(len(self.last_trace), 16)

    def test_export_trace_discriminates_guard_and_read_failures_without_private_strings(self):
        buckets = {"empty": "resultCount", "private-name": "resultNames", "directory-result": "resultNames",
                   "remote": "nonFile", "foreign-host": "foreignHost", "source-alias": "sourceAlias",
                   "empty-expected": "expectedSize", "array-empty": "resultCount"}
        for mode, bucket in buckets.items():
            with self.subTest(mode=mode):
                value = self.probe(mode, diagnostics="--ui-testing-batch-diagnostics")
                log = "\n".join(self.last_trace)
                self.assertFalse(value["verified"]); self.assertEqual(value["calls"], 0)
                self.assertIn("event=guardRejected bucket=" + bucket, log)
                self.assertNotIn("event=readStart", log)
                for private in ("/private", "private-secret-name", "https://", "file://", "another.pdf"):
                    self.assertNotIn(private, log)
                if mode == "directory-result":
                    self.assertIn("roles=other directoryHints=1", log)
        for mode, domain, code in [("read-error-known", "NSCocoaErrorDomain", 257),
                                   ("read-error-unknown", "other", 93)]:
            value = self.probe(mode, diagnostics="--ui-testing-batch-diagnostics")
            log = "\n".join(self.last_trace)
            self.assertFalse(value["verified"]); self.assertEqual(value["calls"], 1)
            self.assertIn(f"event=readError role=ticket domain={domain} code={code}", log)
            self.assertNotIn("private", log)
            self.assertNotIn("secret", log)

    def test_export_trace_cap_cannot_stop_reads_or_turn_late_events_into_acceptance(self):
        value = self.probe("array-observation-cap", diagnostics="--ui-testing-batch-diagnostics")
        self.assertEqual(len(self.last_trace), 16)
        self.assertTrue(value["verified"]); self.assertEqual(value["calls"], 2)
        value = self.probe("array-failed-then-valid", diagnostics="--ui-testing-batch-diagnostics")
        self.assertFalse(value["verified"]); self.assertEqual(value["calls"], 0)
        self.assertIn("event=didPick callback=2 phase=failed urls=2 roles=ticket,insurance", "\n".join(self.last_trace))
        self.assertIn("event=lateIgnored phase=failed", "\n".join(self.last_trace))

    def test_export_trace_matches_reversed_roles_and_waits_for_second_read(self):
        self.probe("array-reverse", diagnostics="--ui-testing-batch-diagnostics")
        log = "\n".join(self.last_trace)
        self.assertIn("roles=insurance,ticket", log)
        self.assertLess(log.index("event=readStart role=insurance"), log.index("event=readStart role=ticket"))
        self.probe("array-held-success", diagnostics="--ui-testing-batch-diagnostics")
        log = "\n".join(self.last_trace)
        self.assertLess(log.index("event=lateIgnored phase=verifying"), log.index("event=readResult role=insurance"))
        self.assertLess(log.index("event=readResult role=insurance"), log.index("event=terminal phase=verified"))


class PassiveExportObservationGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.scratch.cleanup)
        folder = Path(cls.scratch.name); cls.binary = folder / "passive-export"
        start = UI.index("    private func waitForNativeSeedExport(")
        helper = UI[start:UI.index("    // Combined qualification preserves", start)]
        wait_start = UI.index("    private func wait(")
        helper += UI[wait_start:UI.index("    private func check(", wait_start)]
        code = r'''
import Foundation
final class BatchTestFailure: Error, @unchecked Sendable { let token = UUID() }
struct ObservationError: Error {}
struct Instant: Comparable {
    let milliseconds: Int
    static func < (lhs: Self, rhs: Self) -> Bool { lhs.milliseconds < rhs.milliseconds }
    func advanced(by duration: Duration) -> Self {
        let parts = duration.components
        return Self(milliseconds: milliseconds + Int(parts.seconds * 1000 + parts.attoseconds / 1_000_000_000_000_000))
    }
    func duration(to other: Self) -> Duration { .milliseconds(other.milliseconds - milliseconds) }
    @MainActor static var now: Self { ContinuousClock.now }
}
@MainActor enum ContinuousClock { static var now = Instant(milliseconds: 0) }
@MainActor enum State {
    static var mode = ""
    static var cancelled = false
    static var reads = 0
    static var sleepRequests: [Int] = []
}
@MainActor enum Task {
    static var isCancelled: Bool { State.cancelled }
    static func sleep(for duration: Duration) async throws {
        let before = ContinuousClock.now
        ContinuousClock.now = before.advanced(by: duration)
        State.sleepRequests.append(ContinuousClock.now.milliseconds - before.milliseconds)
        let time = ContinuousClock.now.milliseconds
        if State.mode == "initial-cancel" && time >= 500
            || State.mode == "observation-cancel" && time >= 20000 {
            State.cancelled = true; throw CancellationError()
        }
        if State.mode == "observation-error" && time >= 20000 { throw ObservationError() }
    }
}
@MainActor final class XCUIApplication {}
@MainActor final class XCUIElement {
    let role: String
    init(_ role: String) { self.role = role }
    var exists: Bool {
        State.reads += 1
        let late = ContinuousClock.now.milliseconds >= 20000
        let success = State.mode == "initial-success" || State.mode == "late-success" && late
        if role == "failure" { return State.mode == "late-failure" && late }
        if role == "navigation" { return !success }
        return success
    }
}
@MainActor final class XCTAttachment {
    enum Lifetime { case keepAlways }
    let text: String
    var name = ""
    var lifetime = Lifetime.keepAlways
    init(string: String) { text = string }
}
@MainActor final class Harness {
    var captures: [String] = []
    var attachments: [String] = []
    var firstFailure: BatchTestFailure?
    func capture(_ app: XCUIApplication, _ message: String,
                 springboard: XCUIApplication? = nil, batchDiagnostic: Bool) {
        captures.append(message)
        if State.mode == "cancel-after-failure" { State.cancelled = true }
        // Missing diagnostics must not affect the thrown original failure.
        if State.mode == "unavailable-capture" { return }
    }
    func add(_ attachment: XCTAttachment) { attachments.append(attachment.text) }
    // ACTUAL_HELPERS
    func run(observe: Bool) async -> String {
        do {
            try await waitForNativeSeedExport(XCUIApplication(), navigation: XCUIElement("navigation"),
                verified: [XCUIElement("ticket"), XCUIElement("insurance")],
                failed: XCUIElement("failure"), observeLateFailure: observe)
            return "returned"
        } catch let error as BatchTestFailure {
            return error === firstFailure ? "original" : "different-failure"
        } catch is CancellationError { return "cancelled" }
        catch { return "other-error" }
    }
}
@main struct Main {
    @MainActor static func main() async throws {
        State.mode = CommandLine.arguments[1]
        let harness = Harness()
        let result = await harness.run(observe: CommandLine.arguments[2] == "1")
        let value: [String: Any] = ["result": result, "elapsed": ContinuousClock.now.milliseconds,
            "captures": harness.captures, "attachments": harness.attachments,
            "maxSleep": State.sleepRequests.max() ?? 0, "reads": State.reads]
        print(String(decoding: try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]), as: UTF8.self))
    }
}
'''
        # Record the actual thrown object at its sole construction site. No
        # condition, loop, timeout or catch in the extracted helpers is changed.
        original = "throw BatchTestFailure(message: message)"
        assert helper.count(original) == 1
        helper = helper.replace(original, "let original = BatchTestFailure(); firstFailure = original; throw original")
        source = folder / "Passive.swift"; source.write_text(code.replace("    // ACTUAL_HELPERS", helper))
        compiled = subprocess.run(["swiftc", "-swift-version", "6", "-strict-concurrency=complete", "-parse-as-library",
                                   str(source), "-o", str(cls.binary)], capture_output=True, text=True, timeout=60)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    def probe(self, mode, observe=True):
        out = subprocess.run([str(self.binary), mode, "1" if observe else "0"],
                             check=True, capture_output=True, text=True, timeout=5)
        value = json.loads(out.stdout)
        self.assertLessEqual(value["maxSleep"], 100)
        return value

    def test_actual_passive_observation_never_turns_late_terminal_into_success(self):
        for mode in ("late-success", "late-failure"):
            with self.subTest(mode=mode):
                value = self.probe(mode)
                self.assertEqual(value["result"], "original")
                self.assertEqual(value["elapsed"], 20000)
                self.assertEqual(len(value["captures"]), 2)
                self.assertEqual(len(value["attachments"]), 1)
                self.assertIn("terminalObserved=true", value["attachments"][0])
                self.assertIn("acceptance=failed", value["attachments"][0])

    def test_actual_passive_observation_expires_once_after_45_seconds(self):
        value = self.probe("persistent")
        self.assertEqual(value["result"], "original")
        self.assertEqual(value["elapsed"], 60000)
        self.assertEqual(len(value["captures"]), 2)
        self.assertEqual(len(value["attachments"]), 1)
        self.assertIn("requestedObservationSeconds=45", value["attachments"][0])
        self.assertIn("terminalObserved=false", value["attachments"][0])

    def test_actual_passive_observation_is_absent_for_normal_success_or_initial_cancellation(self):
        for mode, observe, result, elapsed, captures in (
                ("late-success", False, "original", 15000, 1),
                ("initial-success", True, "returned", 0, 0),
                ("initial-cancel", True, "cancelled", 500, 0),
                ("cancel-after-failure", True, "original", 15000, 1)):
            with self.subTest(mode=mode):
                value = self.probe(mode, observe)
                self.assertEqual((value["result"],value["elapsed"]),(result,elapsed))
                self.assertEqual(len(value["captures"]), captures)
                self.assertEqual(value["attachments"], [])

    def test_actual_passive_observation_preserves_original_after_diagnostic_errors(self):
        for mode, elapsed, captures in (("observation-cancel",20000,1),
                                        ("observation-error",20000,2),
                                        ("unavailable-capture",60000,2)):
            with self.subTest(mode=mode):
                value = self.probe(mode)
                self.assertEqual(value["result"], "original")
                self.assertEqual(value["elapsed"], elapsed)
                self.assertEqual(len(value["captures"]), captures)
                self.assertEqual(len(value["attachments"]),1)
                self.assertIn("acceptance=failed",value["attachments"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
