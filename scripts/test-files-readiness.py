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
    var disabledDuplicates = 0
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
    var transitionRead: String?
    var transitionOccurrence = 1
    var transitionReachesRoot = true
    var reads: [String: Int] = [:]
    init(_ frames: [Snapshot]) { self.frames = frames }
    var current: Snapshot { frames[index] }
    func advance() { index = min(index + 1, frames.count - 1) }
    func didRead(_ name: String) {
        reads[name, default: 0] += 1
        if name == transitionRead && reads[name] == transitionOccurrence {
            frames = [Snapshot(root: transitionReachesRoot)]; index = 0
        }
    }
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
    let enabledOnly: Bool
    init(_ world: World, _ kind: String, enabledOnly: Bool = false) {
        self.world = world; self.kind = kind; self.enabledOnly = enabledOnly
    }
    var control: Control { kind == "location" ? world.current.location : world.current.browse }
    var eligibleCount: Int {
        enabledOnly ? (control.enabled ? control.count - control.disabledDuplicates : 0) : control.count
    }
    var isEnabled: Bool {
        // Unlike isHittable, an ordinary attribute of a missing row is an XCTest failure.
        precondition(eligibleCount == 1, "Missing element attribute read")
        return control.enabled
    }
    var isHittable: Bool {
        world.didRead(kind + ".hittable")
        return eligibleCount == 1 && control.hittable
    }
    func tap() {
        precondition(eligibleCount == 1 && control.enabled && control.hittable)
        world.tap(kind)
    }
}
final class XCUIElementQuery {
    let element: XCUIElement
    init(_ world: World, _ kind: String, enabledOnly: Bool = false) {
        element = XCUIElement(world, kind, enabledOnly: enabledOnly)
    }
    var count: Int {
        let result = element.eligibleCount
        element.world.didRead(element.kind + (element.enabledOnly ? ".enabled-count" : ".raw-count"))
        return result
    }
    func matching(_ predicate: NSPredicate) -> XCUIElementQuery {
        // Evaluate the real Foundation predicate/key, not a string-shaped fake.
        precondition(predicate.evaluate(with: ["enabled": true]))
        precondition(!predicate.evaluate(with: ["enabled": false]))
        return XCUIElementQuery(element.world, element.kind, enabledOnly: true)
    }
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
        case "location-vanishes-after-count", "location-vanishes-after-enabled-count",
             "location-vanishes-at-hittability", "location-vanishes-before-action",
             "location-vanishes-without-root":
            world = World([Snapshot(location: Control(count: 1))])
            world.transitionRead = name == "location-vanishes-after-enabled-count" ? "location.enabled-count"
                : name == "location-vanishes-at-hittability" ? "location.hittable" : "location.raw-count"
            if name == "location-vanishes-before-action" { world.transitionOccurrence = 4 }
            if name == "location-vanishes-without-root" { world.transitionReachesRoot = false; mustFail = true }
        case "browse-vanishes-after-count", "browse-vanishes-after-enabled-count",
             "browse-vanishes-at-hittability", "browse-vanishes-before-action":
            world = World([Snapshot(browse: Control(count: 1))])
            world.transitionRead = name == "browse-vanishes-after-enabled-count" ? "browse.enabled-count"
                : name == "browse-vanishes-at-hittability" ? "browse.hittable" : "browse.raw-count"
            if name == "browse-vanishes-before-action" { world.transitionOccurrence = 2 }
        case "absent": world = World([Snapshot()]); mustFail = true
        case "ambiguous":
            world = World([Snapshot(location: Control(count: 2), browse: Control(count: 2))]); mustFail = true
        case "disabled-duplicates":
            world = World([Snapshot(location: Control(count: 2, disabledDuplicates: 1),
                                    browse: Control(count: 2, disabledDuplicates: 1))]); mustFail = true
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
    def test_route_can_disappear_between_query_and_read_without_spurious_failure(self):
        for route in ('location', 'browse'):
            for boundary in ('after-count', 'after-enabled-count', 'at-hittability', 'before-action'):
                with self.subTest(route=route, boundary=boundary):
                    self.run_case(f'{route}-vanishes-{boundary}')
    def test_disappearing_route_without_verified_root_still_fails(self):
        self.run_case('location-vanishes-without-root')
    def test_absent_controls_fail_without_taps(self): self.run_case('absent')
    def test_ambiguous_controls_fail_without_taps(self): self.run_case('ambiguous')
    def test_disabled_duplicate_does_not_make_raw_route_unique(self): self.run_case('disabled-duplicates')
    def test_disabled_controls_fail_without_taps(self): self.run_case('disabled')
    def test_hidden_controls_fail_without_taps(self): self.run_case('hidden')

    def test_prepare_initializes_real_provider_without_native_folder_creation(self):
        source = SOURCE.read_text()
        prepare = source[source.index('    func testRecoveryPrepareFilesProvider'):source.index('    func testNativeCreateOwnedFilesFolder')]
        self.assertIn('try await presentRecoverySave(app)', prepare)
        self.assertIn('try await reachRecoveryLocalRoot', prepare)
        self.assertIn('directory.count == 0', prepare)
        self.assertIn('app.state == .notRunning', prepare)
        for forbidden in ['newFolder.tap()', 'newFolder.element.tap()', 'field.typeText(', 'create.element.tap()', 'Save"].tap()']:
            self.assertNotIn(forbidden, prepare)
        self.assertLess(prepare.index('directory.count == 0'), prepare.index('app.state == .notRunning'))

    def test_production_call_and_original_deadline_remain(self):
        source = SOURCE.read_text()
        prepare = source[source.index('    func testRecoveryPrepareFilesProvider'):source.index('    func testNativeCreateOwnedFilesFolder')]
        native_folder = source[source.index('    func testNativeCreateOwnedFilesFolder'):source.index('    func testNativeSaveSeedsBothSyntheticOriginals')]
        call = 'try await reachRecoveryLocalRoot(localTitle,'
        self.assertEqual(prepare.count(call), 1)
        self.assertEqual(native_folder.count(call), 1)
        self.assertEqual(source.count(call), 2)
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
    var recentsCount = 0
    var recentsIdentifier = "DOC.browsingRoot Source: com.apple.DocumentManager.RecentDocuments, Title: Recents"
    var recentsTitle = false
    var tabBarCount = 1
    var tabBarIdentifier = "DOC.browsingModeTabBar"
    var browseCount = 1
    var browseLabel = "Browse"
    var browseEnabled = true
    var browseHittable = true
    var destination = false
    var directory = false
    var location = false
    var browse = false
}
final class World {
    var frames: [State]
    var index = 0
    var taps: [String] = []
    var browseFrames = [State(location: true)]
    init(_ frames: [State]) { self.frames = frames }
    var current: State { frames[index] }
    func advance() { index = min(index + 1, frames.count - 1) }
    func count(_ kind: String) -> Int {
        switch kind {
        case "navigation": return current.navigationCount
        case "picker": return current.pickerCount
        case "directory": return current.directory ? 1 : 0
        case "location": return current.location ? 1 : 0
        case "browse": return current.browse ? current.browseCount : 0
        case "recents": return current.recentsCount
        case "tabbar": return current.tabBarCount
        case "absent": return 0
        default: return 1
        }
    }
    func tap(_ kind: String) {
        taps.append(kind)
        switch kind {
        case "browse": frames = browseFrames
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
    var otherElements: XCUIElementQuery { XCUIElementQuery(world, "other") }
    var cells: XCUIElementQuery { XCUIElementQuery(world, "location") }
    var tabBars: XCUIElementQuery { XCUIElementQuery(world, "tabbar") }
}
final class XCUIElement {
    let world: World
    let kind: String
    init(_ world: World, _ kind: String) { self.world = world; self.kind = kind }
    var exists: Bool { world.count(kind) > 0 }
    var isEnabled: Bool { exists && (kind != "browse" || world.current.browseEnabled) }
    var isHittable: Bool { exists && (kind != "browse" || world.current.browseHittable) }
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
    func matching(identifier: String) -> XCUIElementQuery {
        if element.kind == "other" {
            if identifier == "Browse View (Picker)" { return XCUIElementQuery(element.world, "picker") }
            return XCUIElementQuery(element.world, identifier == element.world.current.recentsIdentifier ? "recents" : "absent")
        }
        if element.kind == "tabbar" && identifier != element.world.current.tabBarIdentifier {
            return XCUIElementQuery(element.world, "absent")
        }
        return self
    }
    func matching(_ predicate: NSPredicate) -> XCUIElementQuery {
        if element.kind == "browse" && !predicate.evaluate(with: ["label": element.world.current.browseLabel]) {
            return XCUIElementQuery(element.world, "absent")
        }
        return self
    }
}
struct FixtureFailure: Error {}
final class Harness {
    let world: World
    init(_ world: World) { self.world = world }
    func isRecoveryFolder(_ title: String, navigation: XCUIElement) -> Bool {
        title == "Recents" ? world.current.recentsTitle : world.current.destination
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
        case "recents-route":
            world = World([State(pickerCount: 0, recentsCount: 1, recentsTitle: true, browse: true)])
            expected = ["browse", "location", "directory"]
        case "wrapped-recents":
            world = World([State(recentsCount: 1, recentsTitle: true, browse: true)])
            expected = ["browse", "location", "directory"]
        case "recents-direct-local-root":
            world = World([State(pickerCount: 0, recentsCount: 1, recentsTitle: true, browse: true)])
            world.browseFrames = [State(directory: true)]
            expected = ["browse", "directory"]
        case "recents-remembered-destination":
            world = World([State(pickerCount: 0, recentsCount: 1, recentsTitle: true, browse: true)])
            world.browseFrames = [State(destination: true)]
            expected = ["browse"]
        case "recents-delayed-local-root":
            world = World([State(pickerCount: 0, recentsCount: 1, recentsTitle: true, browse: true)])
            world.browseFrames = [State(browse: true), State(directory: true, browse: true)]
            expected = ["browse", "directory"]
        case "recents-delayed-destination":
            world = World([State(pickerCount: 0, recentsCount: 1, recentsTitle: true, browse: true)])
            world.browseFrames = [State(browse: true), State(destination: true, browse: true)]
            expected = ["browse"]
        case "delayed-recents":
            world = World([State(pickerCount: 0), State(pickerCount: 0, recentsCount: 1, recentsTitle: true, browse: true)])
            expected = ["browse", "location", "directory"]
        case "ambiguous-recents":
            world = World([State(pickerCount: 0, recentsCount: 2, recentsTitle: true, browse: true)]); mustFail = true
        case "wrong-recents-source":
            world = World([State(pickerCount: 0, recentsCount: 1, recentsIdentifier: "Other source", recentsTitle: true, browse: true)]); mustFail = true
        case "wrong-recents-heading":
            world = World([State(pickerCount: 0, recentsCount: 1, browse: true)]); mustFail = true
        case "ambiguous-native-tabs":
            world = World([State(pickerCount: 0, recentsCount: 1, recentsTitle: true, tabBarCount: 2, browse: true)]); mustFail = true
        case "wrong-native-tabs":
            world = World([State(pickerCount: 0, recentsCount: 1, recentsTitle: true, tabBarIdentifier: "Other tabs", browse: true)]); mustFail = true
        case "wrong-browse-label":
            world = World([State(pickerCount: 0, recentsCount: 1, recentsTitle: true, browseLabel: "Other action", browse: true)]); mustFail = true
        case "ambiguous-browse":
            world = World([State(pickerCount: 0, recentsCount: 1, recentsTitle: true, browseCount: 2, browse: true)]); mustFail = true
        case "disabled-browse":
            world = World([State(pickerCount: 0, recentsCount: 1, recentsTitle: true, browseEnabled: false, browse: true)]); mustFail = true
        case "unhittable-browse":
            world = World([State(pickerCount: 0, recentsCount: 1, recentsTitle: true, browseHittable: false, browse: true)]); mustFail = true
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
                     'ambiguous-navigation', 'ambiguous-picker', 'wrong-folder',
                     'recents-route', 'wrapped-recents', 'recents-direct-local-root',
                     'recents-remembered-destination', 'recents-delayed-local-root',
                     'recents-delayed-destination', 'delayed-recents', 'ambiguous-recents',
                     'wrong-recents-source', 'wrong-recents-heading', 'ambiguous-native-tabs',
                     'wrong-native-tabs', 'wrong-browse-label', 'ambiguous-browse',
                     'disabled-browse', 'unhittable-browse']:
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
    func capture(_ app: XCUIApplication, _ message: String, springboard: XCUIApplication?, batchDiagnostic: Bool = false) {
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
        start = source.index('    private func waitForStableShareAction(')
        end = source.index('    func testRecoveryExportFullBackupThroughFiles(', start)
        source = source[start:end]
        call = 'wait("Share sheet action did not stabilize", app: app, timeout: .seconds(40))'
        self.assertEqual(source.count('timeout: .seconds(40)'), 1)
        self.assertIn(call, source)
        self.assertIn('if actions.count == 1, header.count == 1', source)
        self.assertIn('if action.isEnabled, action.isHittable', source)
        self.assertIn('executionTimeAllowance = phase == "prepare" ? 180 : 300', SOURCE.read_text())


class SDKSourceTests(unittest.TestCase):
    def test_complete_file_typechecks_without_fixture_scope(self):
        sdk = subprocess.run(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-path'],
                             capture_output=True, text=True, check=True, timeout=15).stdout.strip()
        platform = subprocess.run(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-platform-path'],
                                  capture_output=True, text=True, check=True, timeout=15).stdout.strip()
        frameworks = str(Path(platform) / 'Developer/Library/Frameworks')
        for source in (SOURCE, ROOT / 'UITests/PrivacySupportUITests.swift'):
            with self.subTest(source=source.name):
                result = subprocess.run(
                    ['xcrun', 'swiftc', '-typecheck', '-swift-version', '6',
                     '-target', 'arm64-apple-ios17.0-simulator', '-sdk', sdk,
                     '-F', frameworks, '-F', str(Path(sdk) / 'Developer/Library/Frameworks'),
                     '-I', str(Path(platform) / 'Developer/usr/lib'), str(source)],
                    capture_output=True, text=True, timeout=45)
                self.assertEqual(result.returncode, 0, result.stderr)

SHARE_FIXTURE = r'''
import Foundation
import CoreGraphics

struct ShareFrame {
    var actions = 1
    var headers = 1
    var enabled = true
    var hittable = true
    var bounds = CGRect(x: 0, y: 0, width: 402, height: 874)
    var action = CGRect(x: 114, y: 295, width: 82, height: 134)
    var header = CGRect(x: 0, y: 78, width: 402, height: 95)
    var identifier = "actionGroupCell"
    var label = "Save to Files"
    var type = 75
}
final class ShareWorld {
    var frames: [ShareFrame]
    var index = 0
    var polls = 0
    var taps = 0
    init(_ frames: [ShareFrame]) { self.frames = frames }
    var current: ShareFrame { frames[min(index, frames.count - 1)] }
}
final class XCUIElement {
    struct ElementType { let rawValue: Int }
    let world: ShareWorld
    let header: Bool
    init(_ world: ShareWorld, header: Bool) { self.world = world; self.header = header }
    var isEnabled: Bool { world.current.enabled }
    var isHittable: Bool { world.current.hittable }
    var frame: CGRect { header ? world.current.header : world.current.action }
    var identifier: String { world.current.identifier }
    var label: String { world.current.label }
    var elementType: ElementType { ElementType(rawValue: world.current.type) }
    func tap() { world.taps += 1 }
}
final class XCUIElementQuery {
    let world: ShareWorld
    let header: Bool
    init(_ world: ShareWorld, header: Bool = false) { self.world = world; self.header = header }
    var count: Int { header ? world.current.headers : world.current.actions }
    var element: XCUIElement { XCUIElement(world, header: header) }
    func matching(identifier: String) -> XCUIElementQuery {
        precondition(header && identifier == "UIActivityContentView")
        return self
    }
}
final class XCUIApplication {
    let world: ShareWorld
    init(_ world: ShareWorld) { self.world = world }
    var navigationBars: XCUIElementQuery { XCUIElementQuery(world, header: true) }
    var frame: CGRect { world.current.bounds }
}
struct ShareFailure: Error {}
@MainActor final class ShareHarness {
    let world: ShareWorld
    init(_ world: ShareWorld) { self.world = world }
    func wait(_ message: String, app: XCUIApplication, timeout: Duration,
              condition: @MainActor () -> Bool) async throws {
        precondition(timeout == .seconds(40))
        for _ in 0..<12 {
            world.polls += 1
            if condition() { return }
            world.index += 1
        }
        throw ShareFailure()
    }
    // ACTUAL_HELPER
    func run() async throws {
        let actions = XCUIElementQuery(world)
        try await waitForStableShareAction(actions, app: XCUIApplication(world))
        actions.element.tap()
    }
}
@main struct Main {
    @MainActor static func main() async {
        let name = CommandLine.arguments[1]
        let ready = ShareFrame()
        var invalid = ready
        var moved = ready
        moved.action.origin.y += 5
        var otherIdentity = ready
        otherIdentity.identifier = "system-action"
        otherIdentity.type = 9
        var expectedPolls = 0
        var frames: [ShareFrame]
        switch name {
        case "ready": frames = [ready]; expectedPolls = 3
        case "late-ready": invalid.actions = 0; frames = [invalid, invalid, ready]; expectedPolls = 5
        case "movement-resets": frames = [ready, ready, moved]; expectedPolls = 5
        case "header-resets": moved = ready; moved.header.origin.y += 5; frames = [ready, ready, moved]; expectedPolls = 5
        case "identity-resets": frames = [ready, ready, otherIdentity]; expectedPolls = 5
        case "unavailable-resets": invalid.actions = 0; frames = [ready, ready, invalid, ready]; expectedPolls = 6
        case "disabled-resets": invalid.enabled = false; frames = [ready, ready, invalid, ready]; expectedPolls = 6
        case "invalid-resets": invalid.action.size.width = 0; frames = [ready, ready, invalid, ready]; expectedPolls = 6
        case "moving": frames = (0..<12).map { i in var f = ready; f.action.origin.y += Double(i); return f }
        case "absent": invalid.actions = 0; frames = [invalid]
        case "ambiguous": invalid.actions = 2; frames = [invalid]
        case "missing-header": invalid.headers = 0; frames = [invalid]
        case "ambiguous-header": invalid.headers = 2; frames = [invalid]
        case "disabled": invalid.enabled = false; frames = [invalid]
        case "hidden": invalid.hittable = false; frames = [invalid]
        case "zero-area": invalid.action.size.width = 0; frames = [invalid]
        case "offscreen": invalid.action.origin.x = -10; frames = [invalid]
        case "invalid-header": invalid.header.size.height = 0; frames = [invalid]
        case "nonfinite": invalid.action.origin.x = .infinity; frames = [invalid]
        default: fatalError("Unknown fixture")
        }
        let world = ShareWorld(frames)
        var failed = false
        do { try await ShareHarness(world).run() } catch { failed = true }
        precondition(failed == (expectedPolls == 0))
        precondition(world.taps == (expectedPolls == 0 ? 0 : 1))
        precondition(world.polls == (expectedPolls == 0 ? 12 : expectedPolls))
        print("PASS " + name)
    }
}
'''


class ShareReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        source = SOURCE.read_text()
        start = source.index('    private func waitForStableShareAction(')
        end = source.index('    func testRecoveryExportFullBackupThroughFiles(', start)
        root = Path(cls.directory.name)
        path = root / 'ShareReadiness.swift'
        path.write_text(SHARE_FIXTURE.replace('    // ACTUAL_HELPER', source[start:end]))
        cls.binary = root / 'share-readiness-tests'
        result = subprocess.run(['/usr/bin/swiftc', '-parse-as-library', str(path), '-o', str(cls.binary)],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)

    def test_share_readiness_convergence_and_rejected_states(self):
        for name in ['ready', 'late-ready', 'movement-resets', 'header-resets', 'identity-resets',
                     'unavailable-resets', 'disabled-resets', 'invalid-resets', 'moving',
                     'absent', 'ambiguous', 'missing-header', 'ambiguous-header', 'disabled',
                     'hidden', 'zero-area', 'offscreen', 'invalid-header', 'nonfinite']:
            with self.subTest(name=name):
                result = subprocess.run([str(self.binary), name], capture_output=True,
                                        text=True, check=True, timeout=5)
                self.assertEqual(result.stdout.strip(), 'PASS ' + name)

    def test_shared_export_path_waits_before_its_single_tap(self):
        source = SOURCE.read_text()
        start = source.index('    private func presentRecoverySave(')
        end = source.index('    private func waitForStableShareAction(', start)
        body = source[start:end]
        self.assertEqual(body.count('saveToFiles.element.tap()'), 1)
        self.assertLess(body.index('try await waitForStableShareAction(saveToFiles, app: app)'),
                        body.index('saveToFiles.element.tap()'))

PREVIEW_FIXTURE = r'''
import Foundation
import CoreGraphics

@MainActor enum ContinuousClock {
    struct Instant: Comparable {
        let time: Duration
        func advanced(by value: Duration) -> Instant { Instant(time: time + value) }
        static func < (a: Instant, b: Instant) -> Bool { a.time < b.time }
    }
    static var elapsed: Duration = .zero
    static var now: Instant { Instant(time: elapsed) }
}
@MainActor enum Task {
    static func sleep(for value: Duration) async throws { ContinuousClock.elapsed += value }
}
struct FakeImage {
    var lines: [String]
    var fails = false
    var ocrTime: Duration = .zero
    var captureTime: Duration = .zero
    var hasPixels = true
}
struct FakeUIImage { let cgImage: FakeImage? }
struct XCUIScreenshot {
    let token: Int
    let image: FakeUIImage
}
@MainActor final class World {
    var images: [FakeImage]
    var captures = 0
    var requests = 0
    var queryReads = 0
    var reads: [String] = []
    var costs: [String: Duration] = [:]
    func read(_ name: String) { reads.append(name); ContinuousClock.elapsed += costs[name] ?? .zero }
    init(_ images: [FakeImage]) { self.images = images }
}
@MainActor final class XCUIElement {
    let identifier: String
    let world: World
    var present = true
    var hittable = true
    var bounds = CGRect(x: 0, y: 100, width: 402, height: 600)
    var exists: Bool { world.read("exists"); return present }
    var isHittable: Bool { world.read("hittable"); return hittable }
    var frame: CGRect { world.read("frame"); return bounds }
    init(_ identifier: String, _ world: World) { self.identifier = identifier; self.world = world }
    func screenshot() -> XCUIScreenshot {
        world.read("screenshot")
        let image = world.images[min(world.captures, world.images.count - 1)]
        world.captures += 1
        ContinuousClock.elapsed += image.captureTime
        return XCUIScreenshot(token: world.captures, image: FakeUIImage(cgImage: image.hasPixels ? image : nil))
    }
}
@MainActor final class XCUIElementQuery {
    let elements: [XCUIElement]
    let world: World
    init(_ elements: [XCUIElement], _ world: World) { self.elements = elements; self.world = world }
    var count: Int { world.read("count"); return elements.count }
    var element: XCUIElement { precondition(elements.count == 1); return elements[0] }
    func matching(identifier: String) -> XCUIElementQuery {
        XCUIElementQuery(elements.filter { $0.identifier == identifier }, world)
    }
}
@MainActor final class XCUIApplication {
    let nodes: [XCUIElement]
    let world: World
    init(_ nodes: [XCUIElement], _ world: World) { self.nodes = nodes; self.world = world }
    var frame: CGRect { world.read("app.frame"); return CGRect(x: 0, y: 0, width: 402, height: 874) }
    var otherElements: XCUIElementQuery { world.queryReads += 1; return XCUIElementQuery(nodes, world) }
}
struct FakeCandidate { let string: String }
struct FakeObservation {
    let string: String
    func topCandidates(_ count: Int) -> [FakeCandidate] {
        precondition(count == 1); return [FakeCandidate(string: string)]
    }
}
let VNRecognizeTextRequestRevision3 = 3
final class VNRecognizeTextRequest {
    enum Level { case fast, accurate }
    var recognitionLevel: Level = .fast
    var recognitionLanguages: [String] = []
    var usesLanguageCorrection = true
    var revision = 0
    var results: [FakeObservation]?
}
struct FixtureFailure: Error {}
@MainActor struct VNImageRequestHandler {
    static var world: World!
    let image: FakeImage
    init(cgImage: FakeImage, options: [String: String]) { precondition(options.isEmpty); image = cgImage }
    func perform(_ requests: [VNRecognizeTextRequest]) throws {
        precondition(requests.count == 1)
        let request = requests[0]
        precondition(request.recognitionLevel == .accurate && request.recognitionLanguages == ["en-US"])
        precondition(!request.usesLanguageCorrection && request.revision == 3)
        Self.world.requests += 1
        ContinuousClock.elapsed += image.ocrTime
        if image.fails { throw FixtureFailure() }
        request.results = image.lines.map { FakeObservation(string: $0) }
    }
}
final class XCTAttachment {
    enum Lifetime { case deleteOnSuccess, keepAlways }
    let text: String
    var name = ""
    var lifetime: Lifetime = .deleteOnSuccess
    init(string: String) { text = string }
}
@MainActor final class PreviewHarness {
    var failures = 0
    var attachments: [XCTAttachment] = []
    func add(_ attachment: XCTAttachment) { precondition(failures == 1); attachments.append(attachment) }
    func failure(_ message: String, app: XCUIApplication) -> FixtureFailure {
        precondition(message == "Restored original PDF content did not render")
        failures += 1
        return FixtureFailure()
    }
    // ACTUAL_HELPER
    func run(_ name: String) async throws {
        let warning = "SYNTHETIC DEMO — NOT VALID FOR TRAVEL"
        let booking = "Sample reservation ABC-000"
        let positive = FakeImage(lines: [warning, "Coast weekend", booking, "Alex Example"])
        let world = World([positive])
        VNImageRequestHandler.world = world
        let node = XCUIElement("QLPreviewControllerView", world)
        var nodes = [node]
        var expected = false
        var expectedCaptures = 1
        switch name {
        case "rendered": expected = true
        case "normalized":
            world.images = [FakeImage(lines: [" SYNTHETIC  DEMO – NOT VALID FOR TRAVEL ", "Sample\treservation ABC-000"])]; expected = true
        case "blank": world.images = [FakeImage(lines: [])]
        case "wrong-scope":
            world.images = [FakeImage(lines: [])]
            nodes.append(XCUIElement("outside-preview-readable-pdf", World([positive])))
        case "only-warning": world.images = [FakeImage(lines: [warning])]
        case "wrong-digits": world.images = [FakeImage(lines: [warning, "Sample reservation ABC-OOO"])]
        case "wrong-case": world.images = [FakeImage(lines: [warning.lowercased(), booking])]
        case "duplicate": world.images = [FakeImage(lines: [warning, warning, booking])]
        case "ocr-error": world.images[0].fails = true
        case "error-until-deadline": world.images[0].fails = true; world.images[0].ocrTime = .seconds(20); expectedCaptures = 2
        case "bounded-lines": world.images = [FakeImage(lines: [String(repeating: "я", count: 4000)], ocrTime: .milliseconds(39900))]
        case "slow-count", "slow-exists", "slow-hittable", "slow-frame", "slow-app.frame":
            world.costs[String(name.dropFirst(5))] = .seconds(41); expectedCaptures = 0
        case "missing-pixels": world.images[0].hasPixels = false
        case "duplicate-preview": nodes.append(XCUIElement("QLPreviewControllerView", world)); expectedCaptures = 0
        case "missing-preview": nodes = []; expectedCaptures = 0
        case "hidden": node.hittable = false; expectedCaptures = 0
        case "absent": node.present = false; expectedCaptures = 0
        case "offscreen": node.bounds.origin.y = 900; expectedCaptures = 0
        case "zero-area": node.bounds.size.height = 0; expectedCaptures = 0
        case "nonfinite": node.bounds.origin.x = .nan; expectedCaptures = 0
        case "capture-overrun": world.images[0].captureTime = .seconds(41)
        case "ocr-overrun", "ocr-at-deadline":
            world.images[0].ocrTime = .seconds(name == "ocr-overrun" ? 41 : 40)
        case "already-expired": expectedCaptures = 0
        case "blank-then-rendered":
            world.images = [FakeImage(lines: []), positive]; expected = true; expectedCaptures = 2
        default: fatalError("Unknown fixture")
        }
        let app = XCUIApplication(nodes, world)
        if ["blank-then-rendered", "ocr-overrun", "ocr-at-deadline", "capture-overrun", "error-until-deadline", "bounded-lines"].contains(name) {
            var acceptedToken: Int?
            do { acceptedToken = try await waitForRenderedSyntheticOriginal(app).screenshot.token }
            catch { precondition(!expected) }
            precondition((acceptedToken != nil) == expected)
            if expected { precondition(acceptedToken == 2 && failures == 0) }
            else {
                precondition(failures == 1 && attachments.count == 1)
                let text = attachments[0].text
                precondition(text.utf8.count <= 2048 && attachments[0].lifetime == .keepAlways)
                if name == "error-until-deadline" { precondition(text.contains("Vision error: domain=") && text.contains("code=")) }
                if name == "ocr-overrun" || name == "ocr-at-deadline" { precondition(text == "Vision completed after the observation deadline") }
                if name == "bounded-lines" { precondition(text.utf8.count >= 2044 && text.hasPrefix("Recognized preview lines:") && !text.contains("�")) }
            }
        } else {
            let deadline = ContinuousClock.now.advanced(by: name == "already-expired" ? .zero : .seconds(40))
            let result = renderedSyntheticOriginal(app, before: deadline)
            precondition((result != nil) == expected)
            if expected { precondition(result?.screenshot.token == 1) }
        }
        precondition(world.captures == expectedCaptures)
        if name.hasPrefix("slow-") {
            let order = ["count", "exists", "hittable", "frame", "app.frame"]
            let index = order.firstIndex(of: String(name.dropFirst(5)))!
            precondition(world.reads == Array(order[...index]) && world.requests == 0)
        }
        if expected { precondition(attachments.isEmpty) }
        if ["capture-overrun", "missing-pixels", "already-expired"].contains(name) {
            precondition(world.requests == 0)
        }
        if name == "already-expired" { precondition(world.queryReads == 0) }
        if ["ocr-overrun", "ocr-at-deadline"].contains(name) { precondition(world.requests == 1 && world.queryReads == 1) }
        print("PASS " + name)
    }
}
@main struct Main {
    @MainActor static func main() async throws { try await PreviewHarness().run(CommandLine.arguments[1]) }
}
'''


class PreviewReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        source = SOURCE.read_text()
        start = source.index('    private struct RenderedOriginalEvidence {')
        end = source.index('    private func reachRecoveryLocalRoot(', start)
        root = Path(cls.directory.name)
        path = root / 'PreviewReadiness.swift'
        path.write_text(PREVIEW_FIXTURE.replace('    // ACTUAL_HELPER', source[start:end]))
        cls.binary = root / 'preview-readiness-tests'
        result = subprocess.run(['/usr/bin/swiftc', '-parse-as-library', str(path), '-o', str(cls.binary)],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)

    def test_rendered_preview_pixels_and_bounded_observations(self):
        for name in ['rendered', 'normalized', 'blank', 'wrong-scope', 'only-warning',
                     'wrong-digits', 'wrong-case', 'duplicate', 'ocr-error', 'missing-pixels',
                     'duplicate-preview', 'missing-preview', 'hidden', 'absent', 'offscreen',
                     'zero-area', 'nonfinite', 'capture-overrun', 'ocr-overrun', 'ocr-at-deadline',
                     'already-expired', 'blank-then-rendered', 'error-until-deadline', 'bounded-lines',
                     'slow-count', 'slow-exists', 'slow-hittable', 'slow-frame', 'slow-app.frame']:
            with self.subTest(name=name):
                result = subprocess.run([str(self.binary), name], capture_output=True,
                                        text=True, check=True, timeout=5)
                self.assertEqual(result.stdout.strip(), 'PASS ' + name)

    def test_recovery_attaches_the_screenshot_that_satisfied_ocr(self):
        source = SOURCE.read_text()
        start = source.index('    func testRecoveryRestoreIntoEmptyFreeLibraryAndOpenOriginal(')
        end = source.index('    private struct RenderedOriginalEvidence {', start)
        body = source[start:end]
        self.assertIn('let rendered = try await waitForRenderedSyntheticOriginal(app)', body)
        self.assertIn('XCTAttachment(screenshot: rendered.screenshot)', body)
        self.assertLess(body.index('add(renderedScreenshot)'),
                        body.index('capture(app, "Recovery restored original'))
        self.assertNotIn('Task.sleep(for: .seconds(5))', body)


SELECTION_DIAGNOSTIC_FIXTURE = r'''
import Foundation

@MainActor enum ContinuousClock {
    struct Instant: Comparable {
        let time: Duration
        func advanced(by duration: Duration) -> Instant { Instant(time: time + duration) }
        func duration(to other: Instant) -> Duration { other.time - time }
        @MainActor static var now: Instant { ContinuousClock.now }
        static func < (lhs: Instant, rhs: Instant) -> Bool { lhs.time < rhs.time }
    }
    static var elapsed: Duration = .zero
    static var now: Instant { Instant(time: elapsed) }
}
@MainActor final class World {
    var reads: [String] = []
    var cost: Duration = .zero
    var costs: [String: Duration] = [:]
    var titleCount = 1
    func record(_ key: String) { reads.append(key); ContinuousClock.elapsed += costs[key] ?? cost }
}
@MainActor final class XCUIElement {
    enum ElementType: Int { case any = 0, button = 9, staticText = 48 }
    let world: World
    let name: String
    let present: Bool
    init(_ world: World, _ name: String, present: Bool = true) {
        self.world = world; self.name = name; self.present = present
    }
    var exists: Bool { world.record(name + ".exists"); return present }
    var isEnabled: Bool { precondition(present); world.record(name + ".enabled"); return true }
    var isHittable: Bool { precondition(present); world.record(name + ".hittable"); return name == "destinationTitle" }
    var isSelected: Bool { precondition(present); world.record(name + ".selected"); return true }
    var frame: String { precondition(present); world.record(name + ".frame"); return "fixture-frame" }
    func descendants(matching type: ElementType) -> XCUIElementQuery {
        precondition(name == "navigation" && type == .any)
        return XCUIElementQuery(XCUIElement(world, "destinationTitle"), count: world.titleCount,
                               name: "destinationTitles")
    }
}
@MainActor final class XCUIElementQuery {
    let file: XCUIElement
    let matches: Int
    let name: String
    init(_ file: XCUIElement, count: Int, name: String = "files") {
        self.file = file; self.matches = count; self.name = name
    }
    var count: Int { file.world.record(name + ".count"); return matches }
    func element(boundBy index: Int) -> XCUIElement {
        precondition(matches == 1 && index == 0)
        file.world.reads.append(file.name + ".resolve")
        return file
    }
    func matching(_ predicate: NSPredicate) -> XCUIElementQuery {
        precondition(name == "destinationTitles")
        for (type, label, expected) in [(48, "fixture", true), (9, "fixture, Actions Menu", true),
                                       (9, "fixture", false), (48, "fixture, Actions Menu", false),
                                       (9, "fixture-other, Actions Menu", false)] {
            precondition(predicate.evaluate(with: ["elementType": type, "label": label]) == expected)
        }
        return self
    }
}
@MainActor final class XCUIApplication {
    enum State: Int { case runningForeground = 4 }
    let world: World
    init(_ world: World) { self.world = world }
    var state: State { world.record("app.state"); return .runningForeground }
}
final class XCTAttachment {
    enum Lifetime { case deleteOnSuccess, keepAlways }
    let string: String
    var name = ""
    var lifetime: Lifetime = .deleteOnSuccess
    init(string: String) { self.string = string }
}
@MainActor final class Harness {
    var attachments: [XCTAttachment] = []
    func add(_ attachment: XCTAttachment) { attachments.append(attachment) }
    // ACTUAL_HELPER
    func run(_ name: String) {
        let world = World()
        let file = XCUIElement(world, "file", present: name != "file-disappeared")
        let count = name == "ambiguous" ? 2 : name == "missing" ? 0 : 1
        let controlsPresent = name != "missing"
        if name == "budget" { world.cost = .seconds(9) }
        if name == "budget-navigation" { world.costs["navigation.exists"] = .seconds(9) }
        if name == "budget-title-count" { world.costs["destinationTitles.count"] = .seconds(9) }
        if name == "budget-title-hittable" { world.costs["destinationTitle.hittable"] = .seconds(9) }
        if name == "ambiguous-title" { world.titleCount = 2 }
        captureRecoverySelectionFailure(app: XCUIApplication(world),
            picker: XCUIElement(world, "picker"),
            navigation: XCUIElement(world, "navigation", present: name != "missing-navigation"),
            folder: "fixture", files: XCUIElementQuery(file, count: count),
            replace: XCUIElement(world, "replace", present: controlsPresent),
            open: XCUIElement(world, "open", present: controlsPresent), started: ContinuousClock.now)
        precondition(attachments.count == 1)
        let result = attachments[0]
        precondition(result.name == "Recovery file selection — failure state" && result.lifetime == .keepAlways)
        precondition(result.string.contains("elapsedSinceTap=") && result.string.contains("diagnosticElapsed="))
        switch name {
        case "complete":
            for field in ["app.state.rawValue=4", "picker.exists=true", "navigation.exists=true",
                          "exactDestination=true", "files.count=1", "file.enabled=true",
                          "file.hittable=false", "file.selected=true", "file.frame=fixture-frame",
                          "replace.enabled=true", "replace.hittable=false", "open.enabled=true", "open.hittable=false"] {
                precondition(result.string.contains(field), field)
            }
        case "missing", "ambiguous":
            precondition(!world.reads.contains("file.resolve"))
            if name == "missing" {
                precondition(result.string.contains("replace.exists=false") && result.string.contains("open.exists=false"))
                precondition(!world.reads.contains("replace.enabled") && !world.reads.contains("open.enabled"))
            }
        case "file-disappeared":
            precondition(result.string.contains("file.exists=false"))
            precondition(!world.reads.contains("file.enabled") && !world.reads.contains("file.frame"))
        case "budget", "budget-navigation", "budget-title-count", "budget-title-hittable":
            var expected = ["app.state"]
            if name != "budget" { expected += ["picker.exists", "navigation.exists"] }
            if ["budget-title-count", "budget-title-hittable"].contains(name) {
                expected += ["destinationTitles.count"]
            }
            if name == "budget-title-hittable" {
                expected += ["destinationTitle.resolve", "destinationTitle.hittable"]
            }
            precondition(world.reads == expected)
            precondition(result.string.contains("not sampled (diagnostic budget exhausted)"))
            if name != "budget-title-hittable" {
                precondition(result.string.contains("exactDestination=not sampled"))
            }
        case "missing-navigation", "ambiguous-title":
            precondition(result.string.contains("exactDestination=false"))
            precondition(!world.reads.contains("destinationTitle.resolve"))
            if name == "missing-navigation" { precondition(!world.reads.contains("destinationTitles.count")) }
        default: fatalError("Unknown fixture")
        }
        precondition(Set(world.reads).count == world.reads.count, "Diagnostic must not poll or retry")
        print("PASS " + name)
    }
}
@main struct Main {
    @MainActor static func main() { Harness().run(CommandLine.arguments[1]) }
}
'''


class SelectionDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        source = SOURCE.read_text()
        start = source.index('    private func captureRecoverySelectionFailure(')
        end = source.index('    private func capture(', start)
        root = Path(cls.directory.name)
        path = root / 'SelectionDiagnostic.swift'
        path.write_text(SELECTION_DIAGNOSTIC_FIXTURE.replace('    // ACTUAL_HELPER', source[start:end]))
        cls.binary = root / 'selection-diagnostic-tests'
        result = subprocess.run(['/usr/bin/swiftc', '-parse-as-library', str(path), '-o', str(cls.binary)],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)

    def test_failure_state_handles_disappearing_ambiguous_and_slow_controls(self):
        for name in ['complete', 'missing', 'ambiguous', 'file-disappeared', 'budget',
                     'budget-navigation', 'budget-title-count', 'budget-title-hittable',
                     'missing-navigation', 'ambiguous-title']:
            with self.subTest(name=name):
                result = subprocess.run([str(self.binary), name], capture_output=True,
                                        text=True, check=True, timeout=5)
                self.assertEqual(result.stdout.strip(), 'PASS ' + name)


TAB_FIXTURE = r'''
import Foundation
import CoreGraphics

@MainActor struct ContinuousClock {
    struct Instant: Comparable {
        let time: Duration
        func advanced(by duration: Duration) -> Instant { Instant(time: time + duration) }
        func duration(to other: Instant) -> Duration { other.time - time }
        static func < (lhs: Instant, rhs: Instant) -> Bool { lhs.time < rhs.time }
    }
    static var elapsed: Duration = .zero
    var now: Instant { Instant(time: Self.elapsed) }
}
@MainActor enum Task {
    static func sleep(for duration: Duration) async throws { ContinuousClock.elapsed += duration }
}
enum ElementType { case other, button, navigationBar }
@MainActor final class XCUIElementSnapshot {
    var elementType: ElementType
    var label: String
    var identifier: String
    var frame: CGRect
    var isEnabled = true
    var isSelected = false
    var storedChildren: [XCUIElementSnapshot] = []
    var traversalCost: Duration = .zero
    var children: [XCUIElementSnapshot] {
        ContinuousClock.elapsed += traversalCost
        return storedChildren
    }
    init(_ type: ElementType, _ label: String = "", _ identifier: String = "", _ frame: CGRect) {
        elementType = type; self.label = label; self.identifier = identifier; self.frame = frame
    }
}
@MainActor final class World {
    let name: String
    var taps = 0
    var snapshots = 0
    var navigationQueries = 0
    var failures = 0
    var tappedAt: Duration = .zero
    init(_ name: String) { self.name = name }
    func snapshot() -> XCUIElementSnapshot {
        snapshots += 1
        ContinuousClock.elapsed += taps == 0 ? .milliseconds(500) :
            (name == "late-snapshot" ? .seconds(5) : .milliseconds(500))
        let bounds = CGRect(x: 0, y: 0, width: 1032, height: 1376)
        let root = XCUIElementSnapshot(.other, "", "", bounds)
        let frame = CGRect(x: 545, y: 41, width: 97, height: 32.5)
        let leaf = XCUIElementSnapshot(.button, "Settings", "gearshape", frame)
        leaf.isSelected = taps > 0 && name != "unselected"
        if name == "single-button" { root.storedChildren = [leaf] }
        else {
            let parent = XCUIElementSnapshot(.button, "Settings", "gearshape", frame)
            parent.storedChildren = [leaf]; root.storedChildren = [parent]
        }
        if name == "ambiguous-tab" { root.storedChildren.append(XCUIElementSnapshot(.button, "Settings", "gearshape", frame)) }
        if taps > 0 {
            let nav = XCUIElementSnapshot(.navigationBar, "", name == "wrong-navigation" ? "Trips" : "Settings",
                                         CGRect(x: 0, y: 32, width: 1032, height: 116))
            if name == "label-navigation" { nav.identifier = ""; nav.label = "Settings" }
            if name == "offscreen-navigation" { nav.frame.origin.x = -20 }
            if name == "empty-navigation" { nav.frame.size.height = 0 }
            if name == "infinite-navigation" { nav.frame.origin.y = .infinity }
            if name != "missing-navigation" { root.storedChildren.append(nav) }
            if name == "ambiguous-navigation" { root.storedChildren.append(nav) }
            if name == "late-traversal" { root.traversalCost = .seconds(5) }
            if name == "too-deep" {
                var child = root
                for _ in 0..<42 {
                    let next = XCUIElementSnapshot(.other, "", "", .zero)
                    child.storedChildren.append(next); child = next
                }
            }
            if name == "too-many-nodes" {
                root.storedChildren += (0..<1000).map { _ in XCUIElementSnapshot(.other, "", "", .zero) }
            }
        }
        return root
    }
}
@MainActor final class XCUIElement {
    let world: World
    init(_ world: World) { self.world = world }
    var isEnabled: Bool { true }
    var isHittable: Bool { world.name != "unhittable-tab" }
    // The old second remote navbar query consumed 8.2s after a ready snapshot.
    // Keep it available so this fixture fails if that query is reintroduced.
    var exists: Bool {
        world.navigationQueries += 1
        ContinuousClock.elapsed += .milliseconds(8200)
        return true
    }
    func tap() { world.taps += 1; world.tappedAt = ContinuousClock.elapsed }
}
@MainActor final class XCUIElementQuery {
    let world: World
    init(_ world: World) { self.world = world }
    func matching(_ predicate: NSPredicate) -> XCUIElementQuery { self }
    func children(matching type: ElementType) -> XCUIElementQuery { self }
    var element: XCUIElement { XCUIElement(world) }
    subscript(_ identifier: String) -> XCUIElement { XCUIElement(world) }
}
@MainActor final class XCUIApplication {
    let world: World
    init(_ world: World) { self.world = world }
    func snapshot() throws -> XCUIElementSnapshot { world.snapshot() }
    var buttons: XCUIElementQuery { XCUIElementQuery(world) }
    var navigationBars: XCUIElementQuery { XCUIElementQuery(world) }
}
struct FixtureFailure: Error {}
@MainActor final class Harness {
    func require(_ value: Bool, app: XCUIApplication, _ message: String) throws {
        if !value { app.world.failures += 1; throw FixtureFailure() }
    }
    // ACTUAL_HELPER
    func run(_ app: XCUIApplication) async throws {
        try await selectTab("Settings", navigationTitle: "Settings", failure: "Settings did not open", in: app)
    }
}
@main struct Main {
    @MainActor static func main() async {
        let name = CommandLine.arguments[1], world = World(CommandLine.arguments[1])
        let success = ["ready", "single-button", "label-navigation"].contains(name)
        let beforeTapFailure = ["ambiguous-tab", "unhittable-tab"].contains(name)
        var failed = false
        do { try await Harness().run(XCUIApplication(world)) } catch { failed = true }
        precondition(failed != success)
        precondition(world.taps == (beforeTapFailure ? 0 : 1))
        precondition(world.navigationQueries == 0)
        precondition(world.failures == (success ? 0 : 1))
        if success { precondition(world.snapshots == 2 && ContinuousClock.elapsed < .seconds(5)) }
        if name == "late-snapshot" || name == "late-traversal" { precondition(world.snapshots == 2) }
        print("PASS " + name)
    }
}
'''


class TabNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        source = (ROOT / 'UITests/PrivacySupportUITests.swift').read_text()
        start = source.index('    private func selectTab(')
        end = source.index('    private func scrollTo(', start)
        path = Path(cls.directory.name) / 'TabNavigation.swift'
        path.write_text(TAB_FIXTURE.replace('    // ACTUAL_HELPER', source[start:end]))
        cls.binary = Path(cls.directory.name) / 'tab-navigation-tests'
        result = subprocess.run(['/usr/bin/swiftc', '-parse-as-library', str(path), '-o', str(cls.binary)],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)

    def test_one_snapshot_proves_selected_tab_and_unique_visible_navigation(self):
        for name in ['ready', 'single-button', 'label-navigation', 'unselected', 'missing-navigation',
                     'wrong-navigation', 'ambiguous-navigation', 'offscreen-navigation', 'empty-navigation',
                     'infinite-navigation', 'late-snapshot', 'late-traversal', 'too-deep', 'too-many-nodes',
                     'ambiguous-tab', 'unhittable-tab']:
            with self.subTest(name=name):
                result = subprocess.run([str(self.binary), name], capture_output=True,
                                        text=True, check=True, timeout=5)
                self.assertEqual(result.stdout.strip(), 'PASS ' + name)


if __name__ == '__main__':
    unittest.main(verbosity=2)
