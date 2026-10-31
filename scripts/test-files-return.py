"""Execute the actual one-action Swift confirmation helper without a simulator.

The fixture observes dispatch and rejection, not whether native Files implements
Return as a successful commit. Only the retained native postcondition can prove
that. No test text, selector or timeout is substituted into the helper.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'UITests/BatchImportUITests.swift'

FIXTURE = r'''
import Foundation

enum KeyboardKey { case `return` }
final class World { var actions: [String] = [] }
final class XCUIApplication {}
final class XCUIElement {
    let world: World
    let name: String
    var exists = true
    var isEnabled = true
    var isHittable = true
    var identifier: String
    var value: Any?
    init(_ world: World, _ name: String, identifier: String = "", value: String = "") {
        self.world = world; self.name = name
        self.identifier = identifier; self.value = value
    }
    func typeKey(_ key: KeyboardKey, modifierFlags: [String]) {
        precondition(key == .return && modifierFlags.isEmpty)
        world.actions.append(name + ":return")
    }
    func tap() { world.actions.append(name + ":tap") }
}
final class XCUIElementQuery {
    var count: Int
    let element: XCUIElement
    init(_ count: Int, _ element: XCUIElement) { self.count = count; self.element = element }
}
struct FixtureFailure: Error {}
final class Harness {
    let expectedFolder = "TripDocket-Recovery-01234567-89AB-CDEF-0123-456789ABCDEF"
    func check(_ condition: Bool, app: XCUIApplication, _ message: String) throws {
        if !condition { throw FixtureFailure() }
    }
    // ACTUAL_HELPER
    func run(field: XCUIElement, inline: Bool, names: XCUIElementQuery,
             alerts: XCUIElementQuery, create: XCUIElementQuery) throws {
        try confirmRecoveryFolderName(field, recoveryFolder: expectedFolder, inlineNaming: inline, inlineNames: names,
                                      alertNames: alerts, create: create, app: XCUIApplication())
    }
}
@main struct Main {
    static func main() {
        let scenario = CommandLine.arguments[1]
        let world = World(), harness = Harness()
        let field = XCUIElement(world, "field", identifier: "DOC.inlineRenameField", value: harness.expectedFolder)
        let confirmation = XCUIElement(world, "confirmation")
        let names = XCUIElementQuery(1, field), alerts = XCUIElementQuery(0, field)
        let create = XCUIElementQuery(1, confirmation)
        var inline = true, shouldFail = true, expected: [String] = []
        switch scenario {
        case "inline": shouldFail = false; expected = ["field:return"]
        case "alert":
            inline = false; names.count = 0; alerts.count = 1
            shouldFail = false; expected = ["confirmation:tap"]
        case "changed-name": field.value = "unowned-folder"
        case "missing-field": field.exists = false
        case "disabled-field": field.isEnabled = false
        case "hidden-field": field.isHittable = false
        case "wrong-identifier": field.identifier = "document-export-filename"
        case "ambiguous-inline": names.count = 2
        case "missing-inline": names.count = 0
        case "simultaneous-alert": alerts.count = 1
        case "missing-confirmation": create.count = 0
        case "ambiguous-confirmation": create.count = 2
        case "disabled-confirmation": confirmation.isEnabled = false
        case "hidden-confirmation": confirmation.isHittable = false
        case "ambiguous-alert": inline = false; names.count = 0; alerts.count = 2
        default: fatalError("Unknown synthetic scenario")
        }
        var failed = false
        do { try harness.run(field: field, inline: inline, names: names, alerts: alerts, create: create) }
        catch { failed = true }
        guard failed == shouldFail, world.actions == expected else { print("FAIL " + scenario); exit(1) }
        print("PASS " + scenario)
    }
}
'''


class ReturnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        source = SOURCE.read_text()
        start = source.index('    private func confirmRecoveryFolderName(')
        end = source.index('    private func presentRecoverySave(', start)
        helper = source[start:end]
        root = Path(cls.directory.name)
        path = root / 'Return.swift'
        path.write_text(FIXTURE.replace('    // ACTUAL_HELPER', helper))
        cls.binary = root / 'return-tests'
        subprocess.run(['/usr/bin/swiftc', '-parse-as-library', str(path), '-o', str(cls.binary)],
                       capture_output=True, check=True, timeout=45)

    def run_case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True,
                                check=True, timeout=5)
        self.assertEqual(result.stdout.strip(), 'PASS ' + name)

    def test_inline_dispatches_only_return_to_exact_field(self): self.run_case('inline')
    def test_alert_retains_only_existing_confirmation_tap(self): self.run_case('alert')
    def test_changed_name_blocks_every_action(self): self.run_case('changed-name')
    def test_missing_field_blocks_every_action(self): self.run_case('missing-field')
    def test_disabled_field_blocks_every_action(self): self.run_case('disabled-field')
    def test_hidden_field_blocks_every_action(self): self.run_case('hidden-field')
    def test_export_filename_is_not_a_rename_field(self): self.run_case('wrong-identifier')
    def test_duplicate_inline_fields_block_every_action(self): self.run_case('ambiguous-inline')
    def test_missing_inline_field_blocks_every_action(self): self.run_case('missing-inline')
    def test_alert_and_inline_ambiguity_blocks_every_action(self): self.run_case('simultaneous-alert')
    def test_missing_confirmation_blocks_every_action(self): self.run_case('missing-confirmation')
    def test_duplicate_confirmations_block_every_action(self): self.run_case('ambiguous-confirmation')
    def test_disabled_confirmation_blocks_every_action(self): self.run_case('disabled-confirmation')
    def test_hidden_confirmation_blocks_every_action(self): self.run_case('hidden-confirmation')
    def test_alert_ambiguity_blocks_every_action(self): self.run_case('ambiguous-alert')

    def test_call_keeps_exact_name_and_existing_postcondition(self):
        source = SOURCE.read_text()
        start = source.index('    func testRecoveryCreateOwnedFilesDestination')
        end = source.index('    private func confirmRecoveryFolderName(', start)
        body = source[start:end]
        typed = body.index('field.typeText(recoveryFolder)')
        verified = body.index('try check(field.value as? String == recoveryFolder', typed)
        before = body.index('observeCommit("before_done")', verified)
        dispatch = body.index('try confirmRecoveryFolderName(', before)
        after = body.index('observeCommit("after_done")', dispatch)
        postcondition = body.index('inlineNames.count == 0 &&', after)
        self.assertLess(typed, verified)
        self.assertLess(verified, before)
        self.assertLess(before, dispatch)
        self.assertLess(dispatch, after)
        self.assertLess(after, postcondition)
        for operation in ('.tap()', '.press(', '.typeText(', '.typeKey('):
            self.assertNotIn(operation, body[verified:dispatch])
        self.assertEqual(body.count('try confirmRecoveryFolderName('), 1)
        self.assertIn('self.isRecoveryFolder(recoveryFolder, navigation: navigation.element)', body[postcondition:])
        self.assertIn('(directory.count == 1 && directory.element.isHittable)', body[postcondition:])
        self.assertIn('let deadline = ContinuousClock.now.advanced(by: .seconds(15))', source)
        self.assertIn('python3 -B scripts/test-files-return.py', (ROOT / '.github/workflows/ci.yml').read_text())


class SDKSourceTests(unittest.TestCase):
    def test_complete_file_typechecks_without_fixture_scope(self):
        sdk = subprocess.run(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-path'],
                             capture_output=True, text=True, check=True, timeout=15).stdout.strip()
        platform = subprocess.run(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-platform-path'],
                                  capture_output=True, text=True, check=True, timeout=15).stdout.strip()
        frameworks = str(Path(platform) / 'Developer/Library/Frameworks')
        result = subprocess.run(
            ['xcrun', 'swiftc', '-typecheck', '-swift-version', '6',
             '-target', 'arm64-apple-ios17.0-simulator', '-sdk', sdk,
             '-F', frameworks, '-F', str(Path(sdk) / 'Developer/Library/Frameworks'),
             '-I', str(Path(platform) / 'Developer/usr/lib'), str(SOURCE)],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
