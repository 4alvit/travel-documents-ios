"""Execute the actual Swift route helper with fake accessibility state.

This compiles a small portable Swift program, never XCTest or a simulator.
The production helper is extracted unchanged; the fixture supplies only query,
wait and tap boundaries so delayed root arrival exercises the real control flow.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'UITests/BatchImportUITests.swift'

FIXTURE = r'''
import Foundation

struct Control {
    var count = 0
    var enabled = true
    var hittable = true
}
struct Snapshot {
    var root = false
    var location = Control()
    var browse = Control()
}
final class World {
    var frames: [Snapshot]
    var index = 0
    var taps: [String] = []
    var rootAtActionCheck = false
    init(_ frames: [Snapshot]) { self.frames = frames }
    var current: Snapshot { frames[index] }
    func advance() { index = min(index + 1, frames.count - 1) }
    func tap(_ kind: String) {
        taps.append(kind)
        if kind == "browse" {
            frames = [Snapshot(location: Control(count: 1))]
        } else {
            frames = [Snapshot(root: true)]
        }
        index = 0
    }
}
final class XCUIApplication {}
final class XCUIElement {
    let world: World
    let kind: String
    init(_ world: World, _ kind: String) { self.world = world; self.kind = kind }
    var control: Control { kind == "location" ? world.current.location : world.current.browse }
    var isEnabled: Bool { control.enabled }
    var isHittable: Bool { control.hittable }
    func tap() { world.tap(kind) }
}
final class XCUIElementQuery {
    let element: XCUIElement
    init(_ world: World, _ kind: String) { element = XCUIElement(world, kind) }
    var count: Int { element.control.count }
}
struct FixtureFailure: Error {}
final class Harness {
    let world: World
    init(_ world: World) { self.world = world }
    func isRecoveryFolder(_ title: String, navigation: XCUIElement) -> Bool {
        world.current.root
    }
    func check(_ condition: Bool, app: XCUIApplication, _ message: String) throws {
        if !condition { throw FixtureFailure() }
        if world.rootAtActionCheck {
            world.frames = [Snapshot(root: true)]; world.index = 0
        }
    }
    func wait(_ message: String, app: XCUIApplication, condition: () -> Bool) async throws {
        // Advance fake native state between checks, not a second route algorithm.
        for _ in 0..<8 {
            if condition() { return }
            world.advance()
        }
        throw FixtureFailure()
    }
    func run() async throws {
        try await reachRecoveryLocalRoot("On My iPhone",
            navigation: XCUIElementQuery(world, "navigation"),
            location: XCUIElementQuery(world, "location"),
            browse: XCUIElementQuery(world, "browse"), app: XCUIApplication())
    }
    // ACTUAL_HELPER
}

@main struct Main {
    static func main() async throws {
        let name = CommandLine.arguments[1]
        let world: World
        var expected: [String] = []
        var mustFail = false
        switch name {
        case "already-root": world = World([Snapshot(root: true)])
        case "delayed-root": world = World([Snapshot(), Snapshot(), Snapshot(root: true)])
        case "location":
            world = World([Snapshot(location: Control(count: 1))]); expected = ["location"]
        case "browse":
            world = World([Snapshot(browse: Control(count: 1))]); expected = ["browse", "location"]
        case "root-before-action":
            world = World([Snapshot(location: Control(count: 1))]); world.rootAtActionCheck = true
        case "absent": world = World([Snapshot()]); mustFail = true
        case "ambiguous":
            world = World([Snapshot(location: Control(count: 2), browse: Control(count: 2))]); mustFail = true
        case "disabled":
            world = World([Snapshot(location: Control(count: 1, enabled: false),
                                    browse: Control(count: 1, enabled: false))]); mustFail = true
        case "hidden":
            world = World([Snapshot(location: Control(count: 1, hittable: false),
                                    browse: Control(count: 1, hittable: false))]); mustFail = true
        default: fatalError("Unknown fixture")
        }
        var failed = false
        do { try await Harness(world).run() } catch { failed = true }
        guard failed == mustFail, world.taps == expected else { print("FAIL " + name); exit(1) }
        print("PASS " + name)
    }
}
'''


class ReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        source = SOURCE.read_text()
        start = source.index('    private func reachRecoveryLocalRoot(')
        end = source.index('    private func isRecoveryFolder(', start)
        helper = source[start:end]
        root = Path(cls.directory.name)
        path = root / 'Readiness.swift'
        path.write_text(FIXTURE.replace('    // ACTUAL_HELPER', helper))
        cls.binary = root / 'readiness-tests'
        subprocess.run(['/usr/bin/swiftc', '-parse-as-library', str(path), '-o', str(cls.binary)],
                       capture_output=True, check=True, timeout=30)

    def run_case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True,
                                check=True, timeout=5)
        self.assertEqual(result.stdout.strip(), 'PASS ' + name)

    def test_already_at_verified_root_never_navigates(self): self.run_case('already-root')
    def test_delayed_verified_root_arrival_never_requires_browse(self): self.run_case('delayed-root')
    def test_existing_location_route_taps_once(self): self.run_case('location')
    def test_existing_browse_route_remains_bounded(self): self.run_case('browse')
    def test_verified_root_before_action_prevents_redundant_tap(self): self.run_case('root-before-action')
    def test_absent_controls_fail_without_taps(self): self.run_case('absent')
    def test_ambiguous_controls_fail_without_taps(self): self.run_case('ambiguous')
    def test_disabled_controls_fail_without_taps(self): self.run_case('disabled')
    def test_hidden_controls_fail_without_taps(self): self.run_case('hidden')

    def test_prepare_initializes_real_provider_without_native_folder_creation(self):
        source = SOURCE.read_text()
        prepare = source[source.index('    func testRecoveryPrepareFilesProvider'):source.index('    private func presentRecoverySave')]
        self.assertIn('try await presentRecoverySave(app)', prepare)
        self.assertIn('try await reachRecoveryLocalRoot', prepare)
        self.assertIn('directory.count == 0', prepare)
        self.assertIn('app.state == .notRunning', prepare)
        for forbidden in ['newFolder.tap()', 'field.typeText(', 'create.element.tap()', 'Save"].tap()']:
            self.assertNotIn(forbidden, prepare)
        self.assertLess(prepare.index('directory.count == 0'), prepare.index('app.state == .notRunning'))

    def test_production_call_and_original_deadline_remain(self):
        source = SOURCE.read_text()
        self.assertEqual(source.count('try await reachRecoveryLocalRoot(localTitle,'), 1)
        self.assertIn('let deadline = ContinuousClock.now.advanced(by: .seconds(15))', source)
        self.assertIn('titles.count == 1 && titles.element(boundBy: 0).isHittable', source)
        workflow = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertIn('python3 -B scripts/test-files-readiness.py', workflow)


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
            capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
