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
        self.assertIn('timeout: Duration = .seconds(15)', source)
        self.assertIn('let deadline = ContinuousClock.now.advanced(by: timeout)', source)
        self.assertIn('titles.count == 1 && titles.element(boundBy: 0).isHittable', source)
        workflow = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertIn('python3 -B scripts/test-files-readiness.py', workflow)


TITLE_FIXTURE = r'''
import Foundation

final class XCUIElement {
    enum ElementType: Int { case any = 0, button = 9, staticText = 48 }
    let label: String
    let type: ElementType
    let exists: Bool
    let isHittable: Bool
    let children: [XCUIElement]
    init(_ label: String = "", _ type: ElementType = .any,
         exists: Bool = true, hittable: Bool = true, children: [XCUIElement] = []) {
        self.label = label; self.type = type; self.exists = exists
        self.isHittable = hittable; self.children = children
    }
    func descendants(matching: ElementType) -> XCUIElementQuery {
        XCUIElementQuery(children)
    }
}
final class XCUIElementQuery {
    let elements: [XCUIElement]
    init(_ elements: [XCUIElement]) { self.elements = elements }
    var count: Int { elements.count }
    func element(boundBy index: Int) -> XCUIElement { elements[index] }
    func matching(_ predicate: NSPredicate) -> XCUIElementQuery {
        XCUIElementQuery(elements.filter {
            predicate.evaluate(with: ["label": $0.label, "elementType": $0.type.rawValue])
        })
    }
}
final class Harness {
    // ACTUAL_HELPER
    func check(_ navigation: XCUIElement) -> Bool {
        isRecoveryFolder("TripDocket-Recovery-123", navigation: navigation)
    }
}
let folder = "TripDocket-Recovery-123"
let title = XCUIElement(folder, .staticText)
let menu = XCUIElement(folder + ", Actions Menu", .button)
let name = CommandLine.arguments[1]
let children: [XCUIElement]
let expected: Bool
var exists = true
switch name {
case "static-title": children = [title]; expected = true
case "actions-heading": children = [menu]; expected = true
case "other-controls": children = [menu, XCUIElement("Save", .button), XCUIElement("On My iPhone", .button)]; expected = true
case "missing": children = []; expected = false
case "back-button": children = [XCUIElement(folder, .button)]; expected = false
case "wrong-type": children = [XCUIElement(folder + ", Actions Menu", .staticText)]; expected = false
case "other-folder": children = [XCUIElement(folder + "-other, Actions Menu", .button)]; expected = false
case "duplicate": children = [menu, menu]; expected = false
case "two-types": children = [title, menu]; expected = false
case "hidden": children = [XCUIElement(folder + ", Actions Menu", .button, hittable: false)]; expected = false
case "missing-navigation": children = [menu]; exists = false; expected = false
 default: fatalError("Unknown fixture")
}
guard Harness().check(XCUIElement(exists: exists, children: children)) == expected else {
    print("FAIL " + name); exit(1)
}
print("PASS " + name)
'''


class FolderIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        source = SOURCE.read_text()
        start = source.index('    private func isRecoveryFolder(')
        end = source.index('    private func recoveryFilesNavigation(', start)
        path = Path(cls.directory.name) / 'FolderIdentity.swift'
        path.write_text(TITLE_FIXTURE.replace('    // ACTUAL_HELPER', source[start:end]))
        cls.binary = Path(cls.directory.name) / 'folder-identity-tests'
        subprocess.run(['/usr/bin/swiftc', str(path), '-o', str(cls.binary)],
                       capture_output=True, check=True, timeout=30)

    def test_exact_native_headings_and_rejected_distractors(self):
        for name in ['static-title', 'actions-heading', 'other-controls', 'missing',
                     'back-button', 'wrong-type', 'other-folder', 'duplicate',
                     'two-types', 'hidden', 'missing-navigation']:
            with self.subTest(name=name):
                result = subprocess.run([str(self.binary), name], capture_output=True,
                                        text=True, check=True, timeout=5)
                self.assertEqual(result.stdout.strip(), 'PASS ' + name)


OPEN_FOLDER_FIXTURE = r'''
import Foundation

struct State {
    var navigationCount = 1
    var pickerCount = 1
    var destination = false
    var directory = false
    var location = false
    var browse = false
}
final class World {
    var frames: [State]
    var index = 0
    var taps: [String] = []
    init(_ frames: [State]) { self.frames = frames }
    var current: State { frames[index] }
    func advance() { index = min(index + 1, frames.count - 1) }
    func count(_ kind: String) -> Int {
        switch kind {
        case "navigation": return current.navigationCount
        case "picker": return current.pickerCount
        case "directory": return current.directory ? 1 : 0
        case "location": return current.location ? 1 : 0
        case "browse": return current.browse ? 1 : 0
        default: return 1
        }
    }
    func tap(_ kind: String) {
        taps.append(kind)
        switch kind {
        case "browse": frames = [State(location: true)]
        case "location": frames = [State(directory: true)]
        case "directory": frames = [State(destination: true)]
        default: fatalError("Unexpected tap")
        }
        index = 0
    }
}
final class XCUIApplication {
    let world: World
    init(_ world: World) { self.world = world }
    var navigationBars: XCUIElementQuery { XCUIElementQuery(world, "navigation") }
    var otherElements: XCUIElementQuery { XCUIElementQuery(world, "picker") }
    var cells: XCUIElementQuery { XCUIElementQuery(world, "location") }
    var tabBars: XCUIElementQuery { XCUIElementQuery(world, "tabbar") }
}
final class XCUIElement {
    let world: World
    let kind: String
    init(_ world: World, _ kind: String) { self.world = world; self.kind = kind }
    var exists: Bool { world.count(kind) > 0 }
    var isHittable: Bool { exists }
    var firstMatch: XCUIElement { self }
    var cells: XCUIElementQuery { XCUIElementQuery(world, "directory") }
    var buttons: XCUIElementQuery { XCUIElementQuery(world, "browse") }
    func tap() { world.tap(kind) }
}
final class XCUIElementQuery {
    let element: XCUIElement
    init(_ world: World, _ kind: String) { element = XCUIElement(world, kind) }
    var count: Int { element.world.count(element.kind) }
    var firstMatch: XCUIElement { element }
    subscript(_ identifier: String) -> XCUIElement { element }
    func matching(identifier: String) -> XCUIElementQuery { self }
    func matching(_ predicate: NSPredicate) -> XCUIElementQuery { self }
}
struct FixtureFailure: Error {}
final class Harness {
    let world: World
    init(_ world: World) { self.world = world }
    func isRecoveryFolder(_ title: String, navigation: XCUIElement) -> Bool {
        world.current.destination
    }
    func check(_ condition: Bool, app: XCUIApplication, _ message: String) throws {
        if !condition { throw FixtureFailure() }
    }
    func wait(_ message: String, app: XCUIApplication, condition: () -> Bool) async throws {
        for _ in 0..<8 { if condition() { return }; world.advance() }
        throw FixtureFailure()
    }
    func run() async throws { _ = try await openLocalFilesFolder("Exact folder", app: XCUIApplication(world)) }
    // ACTUAL_HELPER
}
@main struct Main {
    static func main() async throws {
        let name = CommandLine.arguments[1]
        let world: World
        var expected: [String] = []
        var mustFail = false
        switch name {
        case "already-current": world = World([State(destination: true)])
        case "delayed-current": world = World([State(), State(destination: true)])
        case "normal-route": world = World([State(browse: true)]); expected = ["browse", "location", "directory"]
        case "ambiguous-navigation": world = World([State(navigationCount: 2, destination: true)]); mustFail = true
        case "ambiguous-picker": world = World([State(pickerCount: 2, destination: true)]); mustFail = true
        case "wrong-folder": world = World([State()]); mustFail = true
        default: fatalError("Unknown fixture")
        }
        var failed = false
        do { try await Harness(world).run() } catch { failed = true }
        guard failed == mustFail, world.taps == expected else { print("FAIL " + name); exit(1) }
        print("PASS " + name)
    }
}
'''


class OpenFolderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        source = SOURCE.read_text()
        start = source.index('    private func openLocalFilesFolder(')
        end = source.index('    private func selectRealFiles(', start)
        path = Path(cls.directory.name) / 'OpenFolder.swift'
        path.write_text(OPEN_FOLDER_FIXTURE.replace('    // ACTUAL_HELPER', source[start:end]))
        cls.binary = Path(cls.directory.name) / 'open-folder-tests'
        subprocess.run(['/usr/bin/swiftc', '-parse-as-library', str(path), '-o', str(cls.binary)],
                       capture_output=True, check=True, timeout=30)

    def test_remembered_destinations_routing_and_ambiguity(self):
        for name in ['already-current', 'delayed-current', 'normal-route',
                     'ambiguous-navigation', 'ambiguous-picker', 'wrong-folder']:
            with self.subTest(name=name):
                result = subprocess.run([str(self.binary), name], capture_output=True,
                                        text=True, check=True, timeout=5)
                self.assertEqual(result.stdout.strip(), 'PASS ' + name)


WAIT_FIXTURE = r'''
import Foundation

final class XCUIApplication {}
struct BatchTestFailure: Error { let message: String }
@MainActor enum ContinuousClock {
    struct Instant: Comparable {
        let time: Duration
        func advanced(by duration: Duration) -> Instant { Instant(time: time + duration) }
        static func < (lhs: Instant, rhs: Instant) -> Bool { lhs.time < rhs.time }
    }
    static var elapsed: Duration = .zero
    static var now: Instant { Instant(time: elapsed) }
}
@MainActor enum Task {
    static var sleeps = 0
    static func sleep(for duration: Duration) async throws {
        sleeps += 1
        ContinuousClock.elapsed += duration
    }
}
@MainActor final class Harness {
    var captures = 0
    func capture(_ app: XCUIApplication, _ message: String, springboard: XCUIApplication?) {
        captures += 1
    }
    // ACTUAL_HELPER
    func run(_ name: String) async throws {
        let readyAt: Duration
        var mustFail = false
        var usesDefault = false
        switch name {
        case "ready": readyAt = .zero
        case "cold-remote": readyAt = .seconds(22)
        case "never-ready": readyAt = .seconds(41); mustFail = true
        case "ordinary-default": readyAt = .seconds(16); mustFail = true; usesDefault = true
        default: fatalError("Unknown fixture")
        }
        let condition = { ContinuousClock.elapsed >= readyAt }
        var failed = false
        do {
            if usesDefault { try await wait("not ready", app: XCUIApplication(), condition: condition) }
            else { try await wait("not ready", app: XCUIApplication(), timeout: .seconds(40), condition: condition) }
        } catch { failed = true }
        guard failed == mustFail, captures == (mustFail ? 1 : 0),
              ContinuousClock.elapsed <= (usesDefault ? .seconds(15) : .seconds(40)) else {
            print("FAIL " + name); exit(1)
        }
        if name == "ready" && Task.sleeps != 0 { exit(1) }
        print("PASS " + name)
    }
}
@main struct Main {
    @MainActor static func main() async throws {
        try await Harness().run(CommandLine.arguments[1])
    }
}
'''


class PresentationWaitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        source = SOURCE.read_text()
        start = source.index('    private func wait(')
        end = source.index('    private func check(', start)
        path = Path(cls.directory.name) / 'PresentationWait.swift'
        path.write_text(WAIT_FIXTURE.replace('    // ACTUAL_HELPER', source[start:end]))
        cls.binary = Path(cls.directory.name) / 'presentation-wait-tests'
        subprocess.run(['/usr/bin/swiftc', '-parse-as-library', str(path), '-o', str(cls.binary)],
                       capture_output=True, check=True, timeout=30)

    def test_remote_readiness_has_one_bounded_wait_and_failure_capture(self):
        for name in ['ready', 'cold-remote', 'never-ready', 'ordinary-default']:
            with self.subTest(name=name):
                result = subprocess.run([str(self.binary), name], capture_output=True,
                                        text=True, check=True, timeout=5)
                self.assertEqual(result.stdout.strip(), 'PASS ' + name)

    def test_extended_budget_is_scoped_to_share_action(self):
        source = SOURCE.read_text()
        call = 'wait("Share sheet has no visible Save to Files action", app: app, timeout: .seconds(40))'
        self.assertEqual(source.count('timeout: .seconds(40)'), 1)
        self.assertIn(call, source)
        self.assertIn('saveToFiles.count == 1 && saveToFiles.element.isEnabled && saveToFiles.element.isHittable', source)
        self.assertIn('executionTimeAllowance = phase == "prepare" ? 120 : 300', source)


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
