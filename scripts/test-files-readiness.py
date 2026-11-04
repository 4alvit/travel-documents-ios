"""Execute the actual Swift route helper with fake accessibility state.

This compiles a small portable Swift program, never XCTest or a simulator.
The production helper is extracted unchanged; the fixture supplies only query,
wait and tap boundaries so delayed root arrival exercises the real control flow.
"""
from pathlib import Path
import json
import os
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
    var rootDelayAfterLocation: Int?
    var locationTapped = false
    var finalWaitElapsed = 0
    var waitSeconds: [Int64] = []
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
        } else if rootDelayAfterLocation != nil {
            locationTapped = true
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
    func wait(_ message: String, app: XCUIApplication, timeout: Duration = .seconds(15),
              condition: () -> Bool) async throws {
        world.waitSeconds.append(timeout.components.seconds)
        if world.locationTapped, let delay = world.rootDelayAfterLocation {
            // Controlled seconds exercise the actual helper's timeout argument
            // without real sleeps or claiming XCTest reads cannot overrun it.
            for second in 0..<Int(timeout.components.seconds) {
                world.finalWaitElapsed = second
                if second >= delay { world.frames = [Snapshot(root: true)]; world.index = 0 }
                if condition() { return }
            }
            world.finalWaitElapsed = Int(timeout.components.seconds)
            throw FixtureFailure()
        }
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
        case "location-root-after-20-seconds", "location-root-after-31-seconds":
            world = World([Snapshot(location: Control(count: 1))]); expected = ["location"]
            world.rootDelayAfterLocation = name == "location-root-after-20-seconds" ? 20 : 31
            mustFail = name == "location-root-after-31-seconds"
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
        if let delay = world.rootDelayAfterLocation {
            guard world.waitSeconds == [15, 15, 30], world.finalWaitElapsed == min(delay, 30)
            else { print("FAIL allowance " + name); exit(1) }
        }
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
                       capture_output=True, check=True, timeout=60)

    def run_case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True,
                                check=True, timeout=5)
        self.assertEqual(result.stdout.strip(), 'PASS ' + name)

    def test_already_at_verified_root_never_navigates(self): self.run_case('already-root')
    def test_delayed_verified_root_arrival_never_requires_browse(self): self.run_case('delayed-root')
    def test_existing_location_route_taps_once(self): self.run_case('location')
    def test_post_tap_root_can_arrive_after_fifteen_seconds_without_retapping(self):
        self.run_case('location-root-after-20-seconds')
    def test_post_tap_root_still_fails_after_thirty_second_allowance(self):
        self.run_case('location-root-after-31-seconds')
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

    def test_prepare_default_retains_provider_only_with_guarded_native_creation(self):
        source = SOURCE.read_text()
        prepare = source[source.index('    func testRecoveryPrepareFilesProvider'):source.index('    func testNativeCreateOwnedFilesFolder')]
        self.assertNotIn('try await presentRecoverySave(app)', prepare)
        self.assertIn('try await reachRecoveryLocalRoot', prepare)
        self.assertIn('directory.count == 0', prepare)
        self.assertIn('app.state == .notRunning', prepare)
        for forbidden in ['newFolder.tap()', 'newFolder.element.tap()', 'field.typeText(', 'create.element.tap()', 'Save"].tap()']:
            self.assertNotIn(forbidden, prepare)
        self.assertLess(prepare.index('directory.count == 0'), prepare.index('app.state == .notRunning'))
        branch = prepare[prepare.index('        if createFolder {'):prepare.index('        // Dedicated Recovery adopts')]
        create, provider = branch.split('        } else {', 1)
        self.assertEqual(create.count('createNativeEmptyFilesFolder('), 1)
        self.assertNotIn('createNativeEmptyFilesFolder(', provider)
        self.assertIn('real local Files provider before fixture shutdown', provider)
        self.assertLess(prepare.index('Self.recoveryNativeFolderCreation('), prepare.index('app.launch()'))
        self.assertIn('directory.count == 0', provider)
        self.assertNotIn('presentRecoverySave(app)', create)
        self.assertLess(create.index('openNativeFilesRoot('), create.index('createNativeEmptyFilesFolder('))
        self.assertLess(prepare.index('try recoveryConfiguration(phase: "prepare")'),
                        prepare.index('let initialObservationTimeout: Duration'))

    def test_production_call_and_original_deadline_remain(self):
        source = SOURCE.read_text()
        prepare = source[source.index('    func testRecoveryPrepareFilesProvider'):source.index('    func testNativeCreateOwnedFilesFolder')]
        native_folder = source[source.index('    func testNativeCreateOwnedFilesFolder'):source.index('    func testNativeSaveSeedsBothSyntheticOriginals')]
        call = 'try await reachRecoveryLocalRoot(localTitle,'
        self.assertEqual(prepare.count(call), 1)
        self.assertEqual(native_folder.count(call), 0)
        self.assertEqual(native_folder.count("try await openNativeFilesRoot(app, initialTimeout: .seconds(30))"), 1)
        self.assertNotIn("presentRecoverySave(app)", native_folder)
        self.assertEqual(source.count(call), 1)
        self.assertIn('timeout: Duration = .seconds(15)', source)
        self.assertIn('let deadline = ContinuousClock.now.advanced(by: timeout)', source)
        self.assertIn('titles.count == 1 && titles.element(boundBy: 0).isHittable', source)
        workflow = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertIn('python3 -B scripts/test-files-readiness.py', workflow)


RECOVERY_MODE_FIXTURE = r'''
import Foundation
struct BatchTestFailure: Error { let message: String }
struct Harness {
    // ACTUAL_HELPER
    // ACTUAL_PROFILE_HELPER
    static func allowance(_ environment: [String: String], _ phase: String, _ debug: Bool) throws -> TimeInterval {
        try recoveryExecutionTimeAllowance(environment, phase: phase, debugIntelSimulator: debug)
    }
    static func run(_ environment: [String: String], _ debug: Bool) throws -> Bool {
        try recoveryNativeFolderCreation(environment, debugSimulator: debug)
    }
    static func sourceArguments(_ folder: String, _ token: String) throws -> [String] {
        try recoveryNativeSourceArguments(folder: folder, sourceToken: token)
    }
}
let data = Data(CommandLine.arguments[1].utf8)
let environment = try JSONDecoder().decode([String: String].self, from: data)
do {
    if CommandLine.arguments.count == 5 {
        print(try Harness.allowance(environment, CommandLine.arguments[3], CommandLine.arguments[2] == "true"))
    } else if CommandLine.arguments.count == 4 {
        let arguments = try Harness.sourceArguments(environment["TRIPDOCKET_RECOVERY_FOLDER"] ?? "",
                                                    CommandLine.arguments[3])
        print(String(data: try JSONEncoder().encode(arguments), encoding: .utf8)!)
    } else {
        print(try Harness.run(environment, CommandLine.arguments[2] == "true") ? "create" : "provider-only")
    }
} catch { print("rejected") }
'''


class RecoveryNativeFolderModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        source = SOURCE.read_text()
        start = source.index('    private static func recoveryNativeFolderCreation(')
        end = source.index('    // Opt-in prepare/export/restore phases.', start)
        helper = source[start:end]
        root = Path(cls.directory.name)
        path = root / 'RecoveryMode.swift'
        profile_start = source.index('    private static func recoveryExecutionTimeAllowance(')
        profile_end = source.index('    private func recoveryTab(', profile_start)
        path.write_text(RECOVERY_MODE_FIXTURE.replace('    // ACTUAL_HELPER', helper)
                        .replace('    // ACTUAL_PROFILE_HELPER', source[profile_start:profile_end]))
        cls.binary = root / 'recovery-mode-tests'
        subprocess.run(['/usr/bin/swiftc', str(path), '-o', str(cls.binary)],
                       capture_output=True, check=True, timeout=60)

    @staticmethod
    def environment():
        return {
            'TRIPDOCKET_RECOVERY_UI': '1',
            'TRIPDOCKET_RECOVERY_PHASE': 'prepare',
            'TRIPDOCKET_RECOVERY_FOLDER': 'TripDocket-Recovery-12345678-1234-4234-8234-123456789abc',
            'TRIPDOCKET_RECOVERY_CREATE_FOLDER': '1',
        }

    def probe(self, environment, debug=True):
        result = subprocess.run([str(self.binary), json.dumps(environment), str(debug).lower()],
                                capture_output=True, text=True, check=True, timeout=5)
        return result.stdout.strip()

    def allowance(self, environment, phase, debug=True):
        result = subprocess.run([str(self.binary), json.dumps(environment), str(debug).lower(), phase, 'allowance'],
                                capture_output=True, text=True, check=True, timeout=5)
        return result.stdout.strip()

    def test_default_native_allowances_do_not_depend_on_host_architecture(self):
        for debug in (False, True):
            for phase, expected in (('prepare', '180.0'), ('export', '300.0'), ('restore', '300.0')):
                with self.subTest(debug=debug, phase=phase):
                    self.assertEqual(self.allowance({}, phase, debug), expected)

    def test_hosted_native_allowances_require_exact_debug_intel_opt_in(self):
        environment = self.environment() | {'TRIPDOCKET_RECOVERY_EXECUTION_PROFILE': 'hosted-intel-v1'}
        for phase, expected in (('prepare', '300.0'), ('export', '600.0'), ('restore', '600.0')):
            current = environment | {'TRIPDOCKET_RECOVERY_PHASE': phase}
            with self.subTest(phase=phase):
                self.assertEqual(self.allowance(current, phase), expected)
                self.assertEqual(self.allowance(current, phase, False), 'rejected')
        for key, values in {
            'TRIPDOCKET_RECOVERY_EXECUTION_PROFILE': ['', 'default', 'hosted-intel-v1 ', 'HOSTED-INTEL-V1'],
            'TRIPDOCKET_RECOVERY_UI': ['', '0', 'true'],
            'TRIPDOCKET_RECOVERY_PHASE': ['', 'export', 'prepare '],
            'TRIPDOCKET_RECOVERY_FOLDER': ['', 'TripDocket-Recovery-provider-probe',
                'TripDocket-Recovery-12345678-1234-4234-8234-123456789ABC',
                'TripDocket-Recovery-12345678-1234-4234-8234-123456789abc/child'],
        }.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    self.assertEqual(self.allowance(environment | {key: value}, 'prepare'), 'rejected')
        for key in ('TRIPDOCKET_RECOVERY_UI', 'TRIPDOCKET_RECOVERY_PHASE', 'TRIPDOCKET_RECOVERY_FOLDER'):
            current = environment.copy(); del current[key]
            self.assertEqual(self.allowance(current, 'prepare'), 'rejected')
        self.assertEqual(self.allowance(environment, 'other'), 'rejected')

    def test_only_explicit_debug_prepare_can_create(self):
        self.assertEqual(self.probe(self.environment()), 'create')
        self.assertEqual(self.probe(self.environment(), debug=False), 'rejected')
        for key, values in {
            'TRIPDOCKET_RECOVERY_CREATE_FOLDER': ['', '0', 'true', '01', ' 1'],
            'TRIPDOCKET_RECOVERY_UI': ['', '0', 'true'],
            'TRIPDOCKET_RECOVERY_PHASE': ['', 'export', 'restore', 'prepare '],
        }.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    self.assertEqual(self.probe(self.environment() | {key: value}), 'rejected')
        for key in ('TRIPDOCKET_RECOVERY_UI', 'TRIPDOCKET_RECOVERY_PHASE', 'TRIPDOCKET_RECOVERY_FOLDER'):
            environment = self.environment()
            del environment[key]
            with self.subTest(missing=key):
                self.assertEqual(self.probe(environment), 'rejected')

    def test_absent_mode_preserves_only_admitted_provider_callers(self):
        environment = self.environment()
        del environment['TRIPDOCKET_RECOVERY_CREATE_FOLDER']
        self.assertEqual(self.probe(environment), 'provider-only')
        self.assertEqual(self.probe(environment, debug=False), 'rejected')
        self.assertEqual(self.probe({}), 'rejected')
        self.assertEqual(self.probe(environment | {'TRIPDOCKET_RECOVERY_FOLDER':
                                                  'TripDocket-Recovery-provider-probe'}), 'rejected')
        for key in ('TRIPDOCKET_RECOVERY_UI', 'TRIPDOCKET_RECOVERY_PHASE', 'TRIPDOCKET_RECOVERY_FOLDER'):
            invalid = environment.copy()
            del invalid[key]
            with self.subTest(missing=key):
                self.assertEqual(self.probe(invalid), 'rejected')
        for key in ('TRIPDOCKET_BATCH_PREPARE_UI', 'TRIPDOCKET_BATCH_PREPARE_TOKEN',
                    'TRIPDOCKET_NATIVE_FOLDER_UI', 'TRIPDOCKET_NATIVE_FOLDER_TOKEN',
                    'TRIPDOCKET_NATIVE_FOLDER_SOURCE_TOKEN', 'TRIPDOCKET_NATIVE_SEED_UI',
                    'TRIPDOCKET_NATIVE_SEED_TOKEN', 'TRIPDOCKET_NATIVE_ROOT_UI',
                    'TRIPDOCKET_NATIVE_ROOT_TOKEN', 'TRIPDOCKET_BATCH_UI',
                    'TRIPDOCKET_BATCH_FOLDER', 'TRIPDOCKET_COMBINED_BATCH_UI',
                    'TRIPDOCKET_BATCH_CHECKPOINT_SESSION', 'TRIPDOCKET_NATIVE_REOPEN_CONTROL'):
            for value in ('', '1'):
                with self.subTest(conflict=key, value=value):
                    self.assertEqual(self.probe(environment | {key: value}), 'rejected')

    def test_native_folder_requires_exact_canonical_recovery_uuid(self):
        for folder in ('', 'TripDocket-Recovery-', 'TripDocket-Recovery-provider-probe',
                       'TripDocket-Recovery-12345678-1234-4234-8234-123456789ABC',
                       'TripDocket-Recovery-{12345678-1234-4234-8234-123456789abc}',
                       'TripDocket-Batch-12345678-1234-4234-8234-123456789abc',
                       'TripDocket-Recovery-12345678-1234-4234-8234-123456789abc/child'):
            with self.subTest(folder=folder):
                self.assertEqual(self.probe(self.environment() | {'TRIPDOCKET_RECOVERY_FOLDER': folder}), 'rejected')

    def test_native_folder_rejects_every_other_ui_mode_even_if_empty(self):
        for key in ('TRIPDOCKET_BATCH_PREPARE_UI', 'TRIPDOCKET_BATCH_PREPARE_TOKEN',
                    'TRIPDOCKET_NATIVE_FOLDER_UI', 'TRIPDOCKET_NATIVE_FOLDER_TOKEN',
                    'TRIPDOCKET_NATIVE_FOLDER_SOURCE_TOKEN', 'TRIPDOCKET_NATIVE_SEED_UI',
                    'TRIPDOCKET_NATIVE_SEED_TOKEN', 'TRIPDOCKET_NATIVE_ROOT_UI',
                    'TRIPDOCKET_NATIVE_ROOT_TOKEN', 'TRIPDOCKET_BATCH_UI',
                    'TRIPDOCKET_BATCH_FOLDER', 'TRIPDOCKET_COMBINED_BATCH_UI',
                    'TRIPDOCKET_BATCH_CHECKPOINT_SESSION', 'TRIPDOCKET_NATIVE_REOPEN_CONTROL'):
            for value in ('', '1'):
                with self.subTest(key=key, value=value):
                    self.assertEqual(self.probe(self.environment() | {key: value}), 'rejected')

    def test_creation_is_confined_to_existing_prepare_phase_and_allowance(self):
        source = SOURCE.read_text()
        config = source[source.index('    private func recoveryConfiguration('):source.index('    private func recoveryTab(')]
        self.assertIn('env["TRIPDOCKET_RECOVERY_CREATE_FOLDER"] == nil || phase == "prepare"', config)
        self.assertIn('#if DEBUG && targetEnvironment(simulator) && arch(x86_64)', config)
        self.assertIn('executionTimeAllowance = try Self.recoveryExecutionTimeAllowance(', config)
        self.assertIn('return phase == "prepare" ? 180 : 300', config)
        self.assertEqual(source.count('try await createNativeEmptyFilesFolder('), 2)
        cases = [line.strip().split('(')[0] for line in source.splitlines() if line.strip().startswith('func testRecovery')]
        self.assertEqual(cases, ['func testRecoveryPrepareFilesProvider', 'func testRecoveryExportFullBackupThroughFiles',
                                 'func testRecoveryRestoreIntoEmptyFreeLibraryAndOpenOriginal'])


    def test_direct_source_arguments_require_distinct_canonical_identity(self):
        source = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        folder = self.environment()['TRIPDOCKET_RECOVERY_FOLDER']
        def arguments(token, destination=folder):
            result = subprocess.run([str(self.binary), json.dumps({'TRIPDOCKET_RECOVERY_FOLDER': destination}),
                                     'true', token], capture_output=True, text=True, check=True, timeout=5)
            return result.stdout.strip()
        self.assertEqual(json.loads(arguments(source)),
                         ['--ui-testing-native-batch-seed', '--ui-testing-native-batch-token', source])
        for token in ('', source.upper(), '{' + source + '}', source + '/child', folder.removeprefix('TripDocket-Recovery-')):
            with self.subTest(token=token):
                self.assertEqual(arguments(token), 'rejected')
        for destination in ('', source, folder.upper(), folder + '/child'):
            with self.subTest(destination=destination):
                self.assertEqual(arguments(source, destination), 'rejected')

    def test_direct_route_has_single_admitted_source_and_common_stop(self):
        source = SOURCE.read_text()
        prepare = source[source.index('    func testRecoveryPrepareFilesProvider'):source.index('    // Batch-only provider initialization.')]
        create, remainder = prepare.split('        if createFolder {', 1)[1].split('        } else {', 1)
        provider, stop = remainder.split('        // Dedicated Recovery adopts', 1)
        self.assertEqual(create.count('UUID().uuidString.lowercased()'), 1)
        self.assertEqual(create.count('app.launch()'), 1)
        self.assertEqual(create.count('source.element.tap()'), 1)
        self.assertLess(create.index('Self.recoveryNativeSourceArguments'), create.index('app.launch()'))
        self.assertIn('app.launchArguments = recoveryArguments + sourceArguments', create)
        self.assertNotIn('--demo', create)
        self.assertIn('app.launchArguments = recoveryArguments + sourceArguments', provider)
        self.assertEqual(provider.count('UUID().uuidString.lowercased()'), 1)
        self.assertEqual(provider.count('source.element.tap()'), 1)
        self.assertIn('reachRecoveryLocalRoot(localTitle,', provider)
        for forbidden in ('--demo', 'presentRecoverySave(app)', 'createNativeEmptyFilesFolder(', 'openNativeFilesRoot('):
            self.assertNotIn(forbidden, provider)
        self.assertIn('app.terminate()', stop)
        self.assertIn('app.state == .notRunning', stop)
        self.assertIn('defer { app.terminate() }', prepare)


DIRECT_RECOVERY_FIXTURE = r'''
import Foundation
struct BatchTestFailure: Error { let message: String }
final class World {
    var count = 1, saved = 0, directoryCount = 0
    var enabled = true, hittable = true, failed = false, navigationReady = true
    var navigationCount = 1, pickerCount = 1
    var navigationExists = true, pickerExists = true
    var presentationDelay: Int?, presentationElapsed = 0
    var events: [String] = []
    var waitSeconds: [Int64] = []
    var folderObservationSeconds: [Int64] = []
    let scenario: String
    init(_ scenario: String) {
        self.scenario = scenario
        if scenario == "missing" { count = 0 }
        if scenario == "ambiguous" { count = 2 }
        if scenario == "disabled" { enabled = false }
        if scenario == "hidden" { hittable = false }
        if scenario == "failed" { failed = true }
        if scenario == "already-saved" { saved = 1 }
        if scenario == "navigation-missing" { navigationReady = false }
        if scenario.contains("after-20-seconds") || scenario.contains("after-31-seconds") {
            presentationDelay = scenario.contains("after-20-seconds") ? 20 : 31
            navigationReady = false
        }
        if scenario.hasPrefix("ambiguous-navigation-") { navigationCount = 2 }
        if scenario.hasPrefix("ambiguous-picker-") { pickerCount = 2 }
        if scenario.hasPrefix("missing-picker-") { pickerCount = 0 }
        if scenario.hasPrefix("absent-navigation-") { navigationExists = false }
        if scenario.hasPrefix("absent-picker-") { pickerExists = false }
        if scenario == "probe-exists" { directoryCount = 1 }
    }
}
enum DeviceIdiom { case phone, pad }
final class UIDevice {
    static let current = UIDevice()
    var userInterfaceIdiom: DeviceIdiom { CommandLine.arguments[1].hasPrefix("ipad-") ? .pad : .phone }
}
final class Element {
    let world: World, kind: String
    init(_ world: World, _ kind: String) { self.world = world; self.kind = kind }
    var exists: Bool {
        if kind == "failure" { return world.failed }
        if kind == "navigation" { return world.navigationReady && world.navigationExists }
        if kind == "picker" { return world.navigationReady && world.pickerExists }
        return world.navigationReady
    }
    var cells: Query { Query(world, "directory") }
    var buttons: Query { Query(world, "browse") }
    var isEnabled: Bool { precondition(world.count == 1); return world.enabled }
    var isHittable: Bool { precondition(world.count == 1); return world.hittable }
    func tap() {
        precondition(kind == "source" && world.count == 1 && world.enabled && world.hittable)
        world.events.append("source-tap")
    }
}
final class Query {
    let world: World, kind: String
    init(_ world: World, _ kind: String) { self.world = world; self.kind = kind }
    var count: Int {
        if kind == "saved" { return world.saved }
        if kind == "directory" { return world.directoryCount }
        if kind == "navigation" { return world.navigationReady ? world.navigationCount : 0 }
        if kind == "picker" { return world.navigationReady ? world.pickerCount : 0 }
        return world.count
    }
    var element: Element { Element(world, kind) }
    func matching(identifier: String) -> Query {
        if kind == "navigation" { precondition(identifier == "FullDocumentManagerViewControllerNavigationBar"); return self }
        if kind == "picker" { precondition(identifier == "Browse View (Picker)"); return self }
        if kind == "directory" {
            precondition(identifier == "TripDocket-Recovery-12345678-1234-4234-8234-123456789abc, Folder")
            return self
        }
        precondition(identifier == "nativeSeed.synthetic-ticket.pdf")
        return Query(world, "source")
    }
    func matching(_ predicate: NSPredicate) -> Query {
        if kind == "cells" {
            precondition(predicate.evaluate(with: ["identifier": "DOC.sidebar.item.On My iPhone"]))
            precondition(predicate.evaluate(with: ["identifier": "DOC.sidebar.item.On My iPad"]))
            precondition(!predicate.evaluate(with: ["identifier": "Other"]))
            return Query(world, "location")
        }
        if kind == "browse" {
            precondition(predicate.evaluate(with: ["label": "Browse"]))
            precondition(!predicate.evaluate(with: ["label": "Other"]))
            return self
        }
        precondition(predicate.evaluate(with: ["identifier": "nativeSeed.saved.synthetic-ticket.pdf"]))
        precondition(!predicate.evaluate(with: ["identifier": "nativeSeed.failure"]))
        return Query(world, "saved")
    }
    subscript(_ identifier: String) -> Element {
        if kind == "tabBars" { precondition(identifier == "DOC.browsingModeTabBar"); return Element(world, "tabBar") }
        precondition(identifier == "nativeSeed.failure"); return Element(world, "failure")
    }
}
final class XCUIApplication {
    let world: World
    var launchArguments: [String] = []
    init(_ world: World) { self.world = world }
    var buttons: Query { Query(world, "buttons") }
    var staticTexts: Query { Query(world, "staticTexts") }
    var navigationBars: Query { Query(world, "navigation") }
    var otherElements: Query { Query(world, "picker") }
    var tabBars: Query { Query(world, "tabBars") }
    var cells: Query { Query(world, "cells") }
    func launch() { world.events.append("launch") }
}
final class Harness {
    let world: World
    let recoveryArguments = ["existing-recovery-arguments"]
    init(_ world: World) { self.world = world }
    // ACTUAL_ARGUMENT_HELPER
    func wait(_ message: String, app: XCUIApplication, timeout: Duration = .seconds(15), condition: () -> Bool) async throws {
        world.waitSeconds.append(timeout.components.seconds)
        if world.events.contains("source-tap") {
            // Controlled seconds exercise the extracted branch's actual timeout
            // and readiness predicate without real sleeps or native UI launches.
            for second in 0..<Int(timeout.components.seconds) {
                world.presentationElapsed = second
                if let delay = world.presentationDelay, second >= delay { world.navigationReady = true }
                if condition() { return }
            }
            world.presentationElapsed = Int(timeout.components.seconds)
            throw BatchTestFailure(message: message)
        }
        if !condition() { throw BatchTestFailure(message: message) }
    }
    func reachRecoveryLocalRoot(_ title: String, navigation: Query, location: Query, browse: Query,
                               app: XCUIApplication) async throws {
        precondition(navigation.kind == "navigation" && location.kind == "location" && browse.kind == "browse")
        world.events.append("generic-root:" + title)
        if world.scenario == "root-failed" { throw BatchTestFailure(message: "root") }
        if world.scenario == "saved-at-root" { world.saved = 1 }
        if world.scenario == "failed-at-root" { world.failed = true }
    }
    func check(_ value: Bool, app: XCUIApplication, _ message: String) throws {
        if !value { throw BatchTestFailure(message: message) }
    }
    func capture(_ app: XCUIApplication, _ label: String) {
        world.events.append("capture")
        if world.scenario == "changed-at-capture" { world.count = 2 }
    }
    func openNativeFilesRoot(_ app: XCUIApplication, initialTimeout: Duration) async throws -> Element {
        precondition(initialTimeout == .seconds(30)); world.events.append("root")
        if world.scenario == "root-failed" { throw BatchTestFailure(message: "root") }
        if world.scenario == "saved-at-root" { world.saved = 1 }
        return Element(world, "picker")
    }
    func createNativeEmptyFilesFolder(_ app: XCUIApplication, picker: Element, ownedFolder: String,
                                     initialObservationTimeout: Duration) async throws {
        precondition(picker.kind == "picker" && ownedFolder == "TripDocket-Recovery-12345678-1234-4234-8234-123456789abc")
        world.folderObservationSeconds.append(initialObservationTimeout.components.seconds)
        world.events.append("create")
        if world.scenario == "saved-at-create" { world.saved = 1 }
        if world.scenario == "failed-at-create" { world.failed = true }
    }
    func run(_ app: XCUIApplication, recoveryFolder: String) async throws {
        // ACTUAL_BRANCH
    }
}
let world = World(CommandLine.arguments[1])
let app = XCUIApplication(world)
var status = "passed"
do { try await Harness(world).run(app, recoveryFolder: "TripDocket-Recovery-12345678-1234-4234-8234-123456789abc") }
catch { status = "rejected" }
print(String(data: try JSONEncoder().encode(["status": [status], "events": world.events,
                                            "arguments": app.launchArguments,
                                            "presentationElapsed": [String(world.presentationElapsed)],
                                            "folderObservationSeconds": world.folderObservationSeconds.map(String.init),
                                            "waitSeconds": world.waitSeconds.map(String.init)]), encoding: .utf8)!)
'''


class DirectRecoveryPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        source = SOURCE.read_text()
        prepare = source[source.index('    func testRecoveryPrepareFilesProvider'):source.index('    // Batch-only provider initialization.')]
        branch = prepare.split('        if createFolder {', 1)[1].split('        } else {', 1)[0]
        start = source.index('    private static func recoveryNativeSourceArguments(')
        helper = source[start:source.index('    // Opt-in prepare/export/restore phases.', start)]
        fixture = DIRECT_RECOVERY_FIXTURE.replace('    // ACTUAL_ARGUMENT_HELPER', helper).replace('        // ACTUAL_BRANCH', branch)
        root = Path(cls.directory.name)
        path = root / 'DirectRecovery.swift'
        path.write_text(fixture)
        cls.binary = root / 'direct-recovery-tests'
        subprocess.run(['/usr/bin/swiftc', str(path), '-o', str(cls.binary)],
                       capture_output=True, check=True, timeout=60)

    def probe(self, scenario, profile=None):
        import os
        env = dict(os.environ)
        env.pop('TRIPDOCKET_RECOVERY_EXECUTION_PROFILE', None)
        if profile is not None:
            env['TRIPDOCKET_RECOVERY_EXECUTION_PROFILE'] = profile
        result = subprocess.run([str(self.binary), scenario], env=env,
                                capture_output=True, text=True, check=True, timeout=5)
        return json.loads(result.stdout)

    def test_actual_direct_branch_opens_once_and_creates_only_after_root(self):
        value = self.probe('ready')
        self.assertEqual(value['status'], ['passed'])
        self.assertEqual(value['events'], ['launch', 'capture', 'source-tap', 'root', 'create', 'capture'])
        self.assertEqual(value['arguments'][:3], ['existing-recovery-arguments', '--ui-testing-native-batch-seed',
                                                '--ui-testing-native-batch-token'])
        import uuid
        token = value['arguments'][3]
        self.assertEqual(str(uuid.UUID(token)), token)
        self.assertNotEqual(token, '12345678-1234-4234-8234-123456789abc')
        self.assertEqual(len(value['arguments']), 4)
        self.assertEqual(value['folderObservationSeconds'], ['30'])

    def test_validated_hosted_profile_selects_only_folder_observation_window(self):
        value = self.probe('ready', 'hosted-intel-v1')
        self.assertEqual(value['status'], ['passed'])
        self.assertEqual(value['folderObservationSeconds'], ['60'])
        self.assertEqual(value['events'], ['launch', 'capture', 'source-tap', 'root', 'create', 'capture'])
        self.assertEqual(value['waitSeconds'], ['15'])

    def test_actual_direct_branch_rejects_unusable_or_changed_source_before_tap(self):
        for scenario in ('missing', 'ambiguous', 'disabled', 'hidden', 'failed', 'already-saved', 'changed-at-capture'):
            with self.subTest(scenario=scenario):
                value = self.probe(scenario)
                self.assertEqual(value['status'], ['rejected'])
                self.assertNotIn('source-tap', value['events'])
                self.assertNotIn('create', value['events'])

    def test_actual_direct_branch_never_creates_after_failed_root_or_export(self):
        for scenario in ('root-failed', 'saved-at-root'):
            with self.subTest(scenario=scenario):
                value = self.probe(scenario)
                self.assertEqual(value['status'], ['rejected'])
                self.assertEqual(value['events'].count('source-tap'), 1)
                self.assertNotIn('create', value['events'])

    def test_actual_direct_branch_rejects_export_or_failure_after_creation(self):
        for scenario in ('saved-at-create', 'failed-at-create'):
            with self.subTest(scenario=scenario):
                value = self.probe(scenario)
                self.assertEqual(value['status'], ['rejected'])
                self.assertEqual(value['events'].count('source-tap'), 1)
                self.assertEqual(value['events'].count('create'), 1)
                self.assertEqual(value['events'][-1], 'create')


class ProviderOnlyPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        source = SOURCE.read_text()
        prepare = source[source.index('    func testRecoveryPrepareFilesProvider'):source.index('    // Batch-only provider initialization.')]
        branch = prepare.split('        } else {', 1)[1].split('        // Dedicated Recovery adopts', 1)[0].rsplit('        }', 1)[0]
        start = source.index('    private static func recoveryNativeSourceArguments(')
        helper = source[start:source.index('    // Opt-in prepare/export/restore phases.', start)]
        fixture = DIRECT_RECOVERY_FIXTURE.replace('    // ACTUAL_ARGUMENT_HELPER', helper).replace('        // ACTUAL_BRANCH', branch)
        root = Path(cls.directory.name)
        path = root / 'ProviderPreparation.swift'
        path.write_text(fixture)
        cls.binary = root / 'provider-preparation-tests'
        subprocess.run(['/usr/bin/swiftc', str(path), '-o', str(cls.binary)],
                       capture_output=True, check=True, timeout=60)

    def probe(self, scenario):
        result = subprocess.run([str(self.binary), scenario], capture_output=True, text=True, check=True, timeout=5)
        return json.loads(result.stdout)

    def test_actual_provider_branch_uses_generic_phone_and_ipad_roots_without_create(self):
        import uuid
        for scenario, title in [('ready', 'On My iPhone'), ('ipad-ready', 'On My iPad')]:
            with self.subTest(scenario=scenario):
                value = self.probe(scenario)
                self.assertEqual(value['status'], ['passed'])
                self.assertEqual(value['events'], ['launch', 'capture', 'source-tap', 'generic-root:' + title, 'capture'])
                self.assertEqual(value['waitSeconds'], ['15', '30'])
                self.assertEqual(value['arguments'][:3], ['existing-recovery-arguments', '--ui-testing-native-batch-seed',
                                                        '--ui-testing-native-batch-token'])
                token = value['arguments'][3]
                self.assertEqual(str(uuid.UUID(token)), token)
                self.assertNotEqual(token, '12345678-1234-4234-8234-123456789abc')
                self.assertEqual(len(value['arguments']), 4)

    def test_actual_provider_accepts_delayed_presentation_without_retapping(self):
        for scenario, title in [('after-20-seconds', 'On My iPhone'),
                                ('ipad-after-20-seconds', 'On My iPad')]:
            with self.subTest(scenario=scenario):
                value = self.probe(scenario)
                self.assertEqual(value['status'], ['passed'])
                self.assertEqual(value['waitSeconds'], ['15', '30'])
                self.assertEqual(value['presentationElapsed'], ['20'])
                self.assertEqual(value['events'], ['launch', 'capture', 'source-tap',
                                                  'generic-root:' + title, 'capture'])

    def test_actual_provider_rejects_late_missing_or_wrong_native_controls_at_bound(self):
        for scenario in ('after-31-seconds', 'navigation-missing',
                         'ambiguous-navigation-after-20-seconds', 'ambiguous-picker-after-20-seconds',
                         'missing-picker-after-20-seconds', 'absent-navigation-after-20-seconds',
                         'absent-picker-after-20-seconds'):
            with self.subTest(scenario=scenario):
                value = self.probe(scenario)
                self.assertEqual(value['status'], ['rejected'])
                self.assertEqual(value['waitSeconds'], ['15', '30'])
                self.assertEqual(value['presentationElapsed'], ['30'])
                self.assertEqual(value['events'], ['launch', 'capture', 'source-tap'])

    def test_actual_provider_branch_rejects_unusable_source_without_tap(self):
        for scenario in ('missing', 'ambiguous', 'disabled', 'hidden', 'failed', 'already-saved', 'changed-at-capture'):
            with self.subTest(scenario=scenario):
                value = self.probe(scenario)
                self.assertEqual(value['status'], ['rejected'])
                self.assertNotIn('source-tap', value['events'])

    def test_actual_provider_branch_rejects_missing_navigation_root_and_occupied_probe(self):
        for scenario in ('navigation-missing', 'root-failed', 'probe-exists'):
            with self.subTest(scenario=scenario):
                value = self.probe(scenario)
                self.assertEqual(value['status'], ['rejected'])
                self.assertEqual(value['events'].count('source-tap'), 1)
                self.assertNotIn('create', value['events'])
                self.assertNotEqual(value['events'][-1], 'capture')

    def test_actual_provider_branch_rejects_export_or_failure_after_root(self):
        for scenario in ('saved-at-root', 'failed-at-root'):
            with self.subTest(scenario=scenario):
                value = self.probe(scenario)
                self.assertEqual(value['status'], ['rejected'])
                self.assertEqual(value['events'].count('source-tap'), 1)
                self.assertEqual(value['events'][-1], 'generic-root:On My iPhone')


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
                       capture_output=True, check=True, timeout=60)

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
    var timeouts: [Duration] = []
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
    func wait(_ message: String, app: XCUIApplication, timeout: Duration = .seconds(15),
              condition: () -> Bool) async throws {
        world.timeouts.append(timeout)
        for _ in 0..<8 { if condition() { return }; world.advance() }
        throw FixtureFailure()
    }
    func run(seedAllowance: Bool = false) async throws {
        if seedAllowance {
            _ = try await openLocalFilesFolder("Exact folder", app: XCUIApplication(world), initialNavigationTimeout: .seconds(30))
        } else {
            _ = try await openLocalFilesFolder("Exact folder", app: XCUIApplication(world))
        }
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
        case "seed-ready": world = World([State(destination: true)])
        case "seed-absent": world = World([State(navigationCount: 0)]); mustFail = true
        case "seed-ambiguous": world = World([State(navigationCount: 2)]); mustFail = true
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
        let seedAllowance = name.hasPrefix("seed-")
        do { try await Harness(world).run(seedAllowance: seedAllowance) } catch { failed = true }
        precondition(world.timeouts.first == (seedAllowance ? .seconds(30) : .seconds(15)))
        precondition(world.timeouts.dropFirst().allSatisfy { $0 == .seconds(15) })
        if name == "seed-absent" || name == "seed-ambiguous" { precondition(world.timeouts.count == 1) }
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
        helper = source[start:end]
        # These existing route cases use the default false opt-in. Keep their
        # original single-tap/wait branch exact; the new full opt-in loop is
        # compiled and executed by RestoreFolderNavigation below.
        boundary = helper.index('        // Preserve the original post-tap destination budget.')
        helper = helper[:boundary] + '        throw FixtureFailure()\n    }\n'
        path.write_text(OPEN_FOLDER_FIXTURE.replace('    // ACTUAL_HELPER', helper))
        cls.binary = Path(cls.directory.name) / 'open-folder-tests'
        subprocess.run(['/usr/bin/swiftc', '-parse-as-library', str(path), '-o', str(cls.binary)],
                       capture_output=True, check=True, timeout=60)

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

    def test_initial_seed_allowance_preserves_later_waits_and_rejects_absent_or_ambiguous_navigation(self):
        for name in ['seed-ready', 'seed-absent', 'seed-ambiguous']:
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
                       capture_output=True, check=True, timeout=60)

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
        self.assertIn('matchingActions.count == 1, matchingHeaders.count == 1', source)
        self.assertIn('if action.isEnabled', source)
        self.assertIn('liveAction.isHittable', source)
        self.assertEqual(source.count('app.snapshot()'), 1)
        self.assertNotIn('actions.count', source)
        self.assertIn('return phase == "prepare" ? 180 : 300', SOURCE.read_text())


SAVE_COMPLETION_FIXTURE = r'''
import Foundation

struct BatchTestFailure: Error { let message: String }
func XCTSkipUnless(_ condition: Bool, _ message: String) throws {
    if !condition { throw BatchTestFailure(message: message) }
}
@MainActor enum ContinuousClock {
    struct Instant: Comparable {
        let time: Duration
        @MainActor func advanced(by duration: Duration) -> Instant {
            ContinuousClock.deadlines += 1
            return Instant(time: time + duration)
        }
        static func < (lhs: Instant, rhs: Instant) -> Bool { lhs.time < rhs.time }
    }
    static var elapsed: Duration = .seconds(9)
    static var deadlines = 0
    static var now: Instant { Instant(time: elapsed) }
}
@MainActor enum Task {
    static func sleep(for duration: Duration) async throws { ContinuousClock.elapsed += duration }
}
@MainActor final class World {
    let scenario: String
    var taps = 0
    var savedAt: Duration = .zero
    init(_ scenario: String) { self.scenario = scenario }
    var completed: Bool { ContinuousClock.elapsed - savedAt >= .seconds(26) }
}
@MainActor struct Element {
    let world: World
    let kind: String
    var exists: Bool {
        if kind == "picker" {
            return world.scenario != "no-settings" && (world.scenario == "pending" || !world.completed)
        }
        return kind == "Settings" && world.scenario != "no-settings"
    }
    func tap() { world.taps += 1; world.savedAt = ContinuousClock.elapsed }
}
@MainActor struct NavigationBars {
    let world: World
    subscript(_ name: String) -> Element { Element(world: world, kind: name) }
}
@MainActor struct XCUIApplication {
    let world: World
    var navigationBars: NavigationBars { NavigationBars(world: world) }
}
@MainActor final class Harness {
    var executionTimeAllowance: TimeInterval = 0
    var continueAfterFailure = true
    var captures = 0
    func capture(_ app: XCUIApplication, _ message: String, springboard: XCUIApplication?,
                 batchDiagnostic: Bool = false) { captures += 1 }
    // ACTUAL_CONFIGURATION
    // ACTUAL_WAIT
    func run(_ scenario: String) async {
        let world = World(scenario)
        var outcome = "passed"
        do {
            // ACTUAL_POLICY
            _ = recoveryFolder
            let app = XCUIApplication(world: world)
            let picker = Element(world: world, kind: "picker")
            let save = Element(world: world, kind: "Save")
            // ACTUAL_SAVE_AND_WAIT
        } catch { outcome = "rejected" }
        let elapsed = (ContinuousClock.elapsed - .seconds(9)).components
        print("\(outcome) \(world.taps) \(captures) \(ContinuousClock.deadlines) \(elapsed.seconds)")
    }
}
@main struct Main {
    @MainActor static func main() async { await Harness().run(CommandLine.arguments[1]) }
}
'''


class RecoverySaveCompletionTests(unittest.TestCase):
    """Run actual configuration, selected allowance and wait with a synthetic clock."""
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        source = SOURCE.read_text()
        start = source.index('    func testRecoveryExportFullBackupThroughFiles(')
        end = source.index('    func testRecoveryRestoreIntoEmptyFreeLibraryAndOpenOriginal(', start)
        cls.export = source[start:end]
        policy = cls.export[cls.export.index('        let recoveryFolder ='):
                            cls.export.index('        let app =')]
        save = cls.export[cls.export.index('        save.tap()'):
                          cls.export.index('        capture(app, "Recovery export — UI completed')]
        start = source.index('    private func recoveryConfiguration(')
        end = source.index('    private func recoveryTab(', start)
        configuration = source[start:end]
        # Stub only the compile-time host boundary; validation itself is unchanged.
        configuration = configuration.replace('#if DEBUG && targetEnvironment(simulator) && arch(x86_64)',
                                              '#if HOSTED_FIXTURE')
        start = source.index('    private func wait(')
        end = source.index('    private func check(', start)
        fixture = (SAVE_COMPLETION_FIXTURE.replace('            // ACTUAL_POLICY', policy)
                   .replace('            // ACTUAL_SAVE_AND_WAIT', save)
                   .replace('    // ACTUAL_CONFIGURATION', configuration)
                   .replace('    // ACTUAL_WAIT', source[start:end]))
        cls.binaries = {}
        for name, flags, text in (
            ('hosted', ['-D', 'HOSTED_FIXTURE'], fixture),
            ('unsupported', [], fixture),
            ('old-cap', ['-D', 'HOSTED_FIXTURE'], fixture.replace(
                '? .seconds(60) : .seconds(15)', '? .seconds(15) : .seconds(15)')),
        ):
            path = Path(cls.directory.name) / (name + '.swift')
            path.write_text(text)
            cls.binaries[name] = path.with_suffix('')
            subprocess.run(['/usr/bin/swiftc', '-parse-as-library', *flags, str(path),
                            '-o', str(cls.binaries[name])], capture_output=True, check=True, timeout=60)

    def probe(self, scenario='delayed', binary='hosted', profile='hosted-intel-v1', **overrides):
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith('TRIPDOCKET_')}
        environment.update(RecoveryNativeFolderModeTests.environment())
        environment['TRIPDOCKET_RECOVERY_PHASE'] = 'export'
        del environment['TRIPDOCKET_RECOVERY_CREATE_FOLDER']
        if profile is not None:
            environment['TRIPDOCKET_RECOVERY_EXECUTION_PROFILE'] = profile
        environment.update(overrides)
        result = subprocess.run([str(self.binaries[binary]), scenario], env=environment,
                                capture_output=True, text=True, check=True, timeout=5)
        return result.stdout.strip()

    def test_hosted_late_completion_passes_once_and_old_cap_mutation_rejects(self):
        self.assertEqual(self.probe(), 'passed 1 0 1 26')
        self.assertEqual(self.probe(binary='old-cap'), 'rejected 1 1 1 15')

    def test_default_stays_fifteen_seconds_on_supported_and_unsupported_builds(self):
        for binary in ('hosted', 'unsupported'):
            with self.subTest(binary=binary):
                self.assertEqual(self.probe(binary=binary, profile=None), 'rejected 1 1 1 15')

    def test_pending_picker_with_settings_behind_never_completes(self):
        self.assertEqual(self.probe(scenario='pending'), 'rejected 1 1 1 60')

    def test_absent_picker_without_settings_never_completes(self):
        self.assertEqual(self.probe(scenario='no-settings'), 'rejected 1 1 1 60')

    def test_invalid_opt_in_rejects_before_save_or_deadline(self):
        for arguments in (
            {'binary': 'unsupported'}, {'profile': 'hosted-intel-v1 '},
            {'TRIPDOCKET_RECOVERY_PHASE': 'restore'},
            {'TRIPDOCKET_RECOVERY_FOLDER': 'TripDocket-Recovery-not-a-uuid'},
            {'TRIPDOCKET_RECOVERY_CREATE_FOLDER': '1'},
        ):
            with self.subTest(arguments=arguments):
                self.assertEqual(self.probe(**arguments), 'rejected 0 0 0 0')

    def test_policy_is_scoped_after_configuration_before_single_save(self):
        self.assertLess(self.export.index('try recoveryConfiguration(phase: "export")'),
                        self.export.index('let saveCompletionTimeout: Duration'))
        self.assertLess(self.export.index('let saveCompletionTimeout: Duration'), self.export.index('save.tap()'))
        self.assertEqual(self.export.count('save.tap()'), 1)
        self.assertEqual(SOURCE.read_text().count('timeout: saveCompletionTimeout'), 1)


class HostedPhoneTimingTests(unittest.TestCase):
    """Execute actual allowance branches with only environment/device/build stubs."""
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        definitions = [
            ('AccessibilityUITests.swift', 'testMaximumTypeFreeCardAndProDismissal', 'let app =', ''),
            ('AccessibilityUITests.swift', 'testMaximumTypeCompleteBackupWarningAndCancellation', 'let app =', ''),
            ('LocalizationUITests.swift', 'testRussianMaximumTypeCompleteBackupWarningAndCancellation', 'let app =', ''),
            ('PrivacySupportUITests.swift', 'verifyGuidance', 'continueAfterFailure =', 'let russian = false; let maximumType = false'),
            ('PrivacySupportUITests.swift', 'verifyGuidance', 'continueAfterFailure =', 'let russian = true; let maximumType = true'),
        ]
        code = '''import Foundation
        @MainActor enum UIDevice {
            enum Idiom { case phone, pad }
            static var current: UIDevice.Type { self }
            static var userInterfaceIdiom: Idiom {
                ProcessInfo.processInfo.environment["PHONE_TEST_IDIOM"] == "pad" ? .pad : .phone
            }
        }
        '''
        for index, (filename, method, stop, locals_) in enumerate(definitions):
            source = (ROOT / 'UITests' / filename).read_text()
            start = source.index('    private enum PhoneTimingError:')
            end = (source.index('    private struct Copy {', start)
                   if filename == 'PrivacySupportUITests.swift' else
                   source.index('\n    private ', source.index('    private func useHostedPhoneTiming()', start) + 10))
            helper = source[start:end]
            condition = '#if DEBUG && arch(x86_64) && targetEnvironment(simulator)'
            assert helper.count(condition) == (2 if filename == 'PrivacySupportUITests.swift' else 1)
            # Native build conditions are separately SDK-typechecked. This fixture
            # executes both actual bodies on any host, without launching XCTest.
            helper = helper.replace(condition, '#if PHONE_TEST_SUPPORTED_BUILD')
            start = source.index('func ' + method + '(')
            start = source.index('{', start) + 1
            prefix = source[start:source.index(stop, start)]
            code += f'\n@MainActor final class Case{index} {{\nvar executionTimeAllowance: Double = 777\n'
            code += helper + '\nfunc run() throws -> Double {\n' + locals_ + prefix
            code += '\nreturn executionTimeAllowance\n}\n}\n'
        code += '''
        @main enum Main {
            @MainActor static func main() {
                func capture(_ action: () throws -> Double) -> String {
                    do { return String(try action()) }
                    catch { return "rejected" }
                }
                let values = [capture { try Case0().run() }, capture { try Case1().run() },
                              capture { try Case2().run() }, capture { try Case3().run() },
                              capture { try Case4().run() }]
                print("[" + values.joined(separator: ", ") + "]")
            }
        }
        '''
        path = Path(cls.directory.name) / 'PhoneTiming.swift'; path.write_text(code)
        cls.binaries = {}
        for supported in (False, True):
            binary = Path(cls.directory.name) / ('supported' if supported else 'unsupported')
            flags = ['-D', 'PHONE_TEST_SUPPORTED_BUILD'] if supported else []
            result = subprocess.run(['/usr/bin/swiftc', '-swift-version', '6', '-parse-as-library',
                                     *flags, str(path), '-o', str(binary)], capture_output=True, text=True, timeout=60)
            if result.returncode != 0: raise AssertionError(result.stderr)
            cls.binaries[supported] = binary

    def invoke(self, supported, token=None, idiom='phone'):
        env = dict(os.environ); env.pop('TRIPDOCKET_PHONE_TIMING', None)
        env.pop('TRIPDOCKET_IPAD_TIMING', None)
        env['PHONE_TEST_IDIOM'] = idiom
        if token is not None: env['TRIPDOCKET_PHONE_TIMING'] = token
        result = subprocess.run([str(self.binaries[supported])], env=env, capture_output=True,
                                text=True, check=True, timeout=5)
        return result.stdout.strip()

    def test_absent_token_preserves_explicit_and_inherited_defaults(self):
        for supported in (False, True):
            for idiom in ('phone', 'pad'):
                self.assertEqual(self.invoke(supported, idiom=idiom), '[777.0, 180.0, 120.0, 480.0, 600.0]')

    def test_exact_supported_phone_profile_changes_only_four_case_branches(self):
        self.assertEqual(self.invoke(True, 'hosted-intel-phone-v1'), '[240.0, 240.0, 240.0, 720.0, 600.0]')

    def test_invalid_token_wrong_build_or_ipad_rejects_before_any_case_body(self):
        for token in ('', 'wrong', 'hosted-intel-phone-v1 '):
            self.assertEqual(self.invoke(True, token), '[rejected, rejected, rejected, rejected, rejected]')
        self.assertEqual(self.invoke(False, 'hosted-intel-phone-v1'), '[rejected, rejected, rejected, rejected, rejected]')
        self.assertEqual(self.invoke(True, 'hosted-intel-phone-v1', 'pad'), '[rejected, rejected, rejected, rejected, rejected]')


class HostedIPadTimingTests(unittest.TestCase):
    """Execute the actual pre-launch selector, including its existing Phone path."""
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        source = (ROOT / 'UITests/PrivacySupportUITests.swift').read_text()
        start = source.index('    private enum PhoneTimingError:')
        helper = source[start:source.index('    private struct Copy {', start)]
        condition = '#if DEBUG && arch(x86_64) && targetEnvironment(simulator)'
        assert helper.count(condition) == 2
        helper = helper.replace(condition, '#if IPAD_TEST_SUPPORTED_BUILD')
        start = source.index('    private func verifyGuidance(')
        start = source.index('{', start) + 1
        prefix = source[start:source.index('        continueAfterFailure =', start)]
        assert 'XCUIApplication' not in helper + prefix
        cls.code = '''import Foundation
        @MainActor enum UIDevice {
            enum Idiom { case phone, pad }
            static var current: UIDevice.Type { self }
            static var userInterfaceIdiom: Idiom {
                ProcessInfo.processInfo.environment["IPAD_TEST_IDIOM"] == "pad" ? .pad : .phone
            }
        }
        @MainActor final class Harness {
            var executionTimeAllowance: Double = 777
        ''' + helper + '''
            func run(russian: Bool, maximumType: Bool) throws -> Double {
        ''' + prefix + '''
                return executionTimeAllowance
            }
        }
        @main enum Main {
            @MainActor static func main() {
                do {
                    let value = try Harness().run(russian: CommandLine.arguments[1] == "true",
                                                  maximumType: CommandLine.arguments[2] == "true")
                    print(value)
                } catch { print("rejected") }
            }
        }
        '''
        cls.binaries = {supported: cls.compile(cls.code, str(supported), supported)
                        for supported in (False, True)}

    @classmethod
    def compile(cls, code, name, supported):
        path = Path(cls.directory.name) / (name + '.swift'); path.write_text(code)
        binary = Path(cls.directory.name) / name
        flags = ['-D', 'IPAD_TEST_SUPPORTED_BUILD'] if supported else []
        result = subprocess.run(['/usr/bin/swiftc', '-swift-version', '6', '-parse-as-library',
                                 *flags, str(path), '-o', str(binary)], capture_output=True,
                                text=True, timeout=60)
        if result.returncode != 0: raise AssertionError(result.stderr)
        return binary

    def invoke(self, supported=True, token=None, phone=None, idiom='pad',
               russian=False, maximum=False, binary=None):
        env = dict(os.environ)
        for key in ('TRIPDOCKET_PHONE_TIMING', 'TRIPDOCKET_IPAD_TIMING'):
            env.pop(key, None)
        env['IPAD_TEST_IDIOM'] = idiom
        if token is not None: env['TRIPDOCKET_IPAD_TIMING'] = token
        if phone is not None: env['TRIPDOCKET_PHONE_TIMING'] = phone
        result = subprocess.run([str(binary or self.binaries[supported]),
                                 str(russian).lower(), str(maximum).lower()],
                                env=env, capture_output=True, text=True, check=True, timeout=5)
        return result.stdout.strip()

    def test_exact_hosted_intel_english_ipad_selector_sets_900(self):
        self.assertEqual(self.invoke(token='hosted-intel-ipad-en-v1'), '900.0')

    def test_exact_hosted_intel_russian_maximum_ipad_selector_sets_1200(self):
        self.assertEqual(self.invoke(token='hosted-intel-ipad-ru-v1',
                                     russian=True, maximum=True), '1200.0')

    def test_missing_ipad_token_preserves_phone_and_both_default_locales(self):
        for supported in (False, True):
            for idiom in ('pad', 'phone'):
                self.assertEqual(self.invoke(supported=supported, idiom=idiom), '480.0')
                self.assertEqual(self.invoke(supported=supported, idiom=idiom,
                                             russian=True, maximum=True), '600.0')
        self.assertEqual(self.invoke(phone='hosted-intel-phone-v1', idiom='phone'), '720.0')
        self.assertEqual(self.invoke(phone='hosted-intel-phone-v1', idiom='phone',
                                     russian=True, maximum=True), '600.0')

    def test_invalid_conflicting_or_out_of_scope_ipad_tokens_reject(self):
        for token in ('', 'wrong', 'hosted-intel-ipad-en-v1 ', 'hosted-intel-ipad-ru-v1 '):
            with self.subTest(token=token):
                self.assertEqual(self.invoke(token=token), 'rejected')
        for kwargs in ({'supported': False}, {'idiom': 'phone'}, {'russian': True},
                       {'maximum': True}, {'russian': True, 'maximum': True},
                       {'phone': ''}, {'phone': 'hosted-intel-phone-v1'}, {'phone': 'wrong'}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.invoke(token='hosted-intel-ipad-en-v1', **kwargs), 'rejected')

    def test_russian_token_rejects_each_wrong_case_build_idiom_or_phone_conflict(self):
        for kwargs in ({'supported': False}, {'idiom': 'phone'}, {'russian': False},
                       {'maximum': False}, {'russian': False, 'maximum': False},
                       {'phone': ''}, {'phone': 'hosted-intel-phone-v1'}, {'phone': 'wrong'}):
            arguments = {'russian': True, 'maximum': True, **kwargs}
            with self.subTest(arguments=arguments):
                self.assertEqual(self.invoke(token='hosted-intel-ipad-ru-v1', **arguments), 'rejected')

    def test_removing_only_native_allowance_loses_required_hosted_behavior(self):
        needle = 'executionTimeAllowance = hostedIPad ? (russian ? 1200 : 900) :'
        self.assertEqual(self.code.count(needle), 1)
        mutated = self.compile(self.code.replace(needle, 'executionTimeAllowance = hostedIPad ? 480 :'),
                               'without-native-allowance', True)
        self.assertEqual(self.invoke(token='hosted-intel-ipad-en-v1', binary=mutated), '480.0')
        self.assertNotEqual(self.invoke(token='hosted-intel-ipad-en-v1', binary=mutated), '900.0')

    def test_reverting_only_russian_native_allowance_loses_required_policy(self):
        needle = 'executionTimeAllowance = hostedIPad ? (russian ? 1200 : 900) :'
        self.assertEqual(self.code.count(needle), 1)
        mutated = self.compile(self.code.replace(needle,
            'executionTimeAllowance = hostedIPad ? (russian ? 600 : 900) :'), 'old-russian-allowance', True)
        self.assertEqual(self.invoke(token='hosted-intel-ipad-ru-v1', russian=True,
                                     maximum=True, binary=mutated), '600.0')
        self.assertNotEqual(self.invoke(token='hosted-intel-ipad-ru-v1', russian=True,
                                        maximum=True, binary=mutated), '1200.0')
        self.assertEqual(self.invoke(token='hosted-intel-ipad-en-v1', binary=mutated), '900.0')


class SDKSourceTests(unittest.TestCase):
    def test_complete_file_typechecks_without_fixture_scope(self):
        sdk = subprocess.run(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-path'],
                             capture_output=True, text=True, check=True, timeout=15).stdout.strip()
        platform = subprocess.run(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-platform-path'],
                                  capture_output=True, text=True, check=True, timeout=15).stdout.strip()
        frameworks = str(Path(platform) / 'Developer/Library/Frameworks')
        for source, target, flags in ((SOURCE, 'arm64', []), (SOURCE, 'x86_64', ['-D', 'DEBUG']),
                                      (ROOT / 'UITests/PrivacySupportUITests.swift', 'arm64', [])):
            with self.subTest(source=source.name, target=target, flags=flags):
                result = subprocess.run(
                    ['xcrun', 'swiftc', '-typecheck', '-swift-version', '6',
                     '-target', target + '-apple-ios17.0-simulator', '-sdk', sdk,
                     '-F', frameworks, '-F', str(Path(sdk) / 'Developer/Library/Frameworks'),
                     '-I', str(Path(platform) / 'Developer/usr/lib'), *flags, str(source)],
                    capture_output=True, text=True, timeout=180)
                self.assertEqual(result.returncode, 0, result.stderr)

SHARE_FIXTURE = r'''
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
struct BatchTestFailure: Error { let message: String }
struct ShareFrame {
    var actions = 1
    var headers = 1
    var enabled = true
    var hittable = true
    var bounds = CGRect(x: 0, y: 0, width: 402, height: 874)
    var action = CGRect(x: 114, y: 295, width: 82, height: 134)
    var header = CGRect(x: 0, y: 78, width: 402, height: 95)
    var headerLabel = ""
    var identifier = "actionGroupCell"
    var label = "Save to Files"
    var type = XCUIElement.ElementType.cell
    var liveIdentifier: String?
    var liveLabel: String?
    var liveType: XCUIElement.ElementType?
    var snapshotFails = false
    var snapshotCost: Duration = .zero
    var hittableCost: Duration = .zero
    var traversalCost: Duration = .zero
    var fillers = 0
    var depth = 0
    var staticTextDecoy = false
    var lateOverflow: String?
}
@MainActor final class XCUIElementSnapshot {
    let elementType: XCUIElement.ElementType
    let identifier: String
    let label: String
    let frame: CGRect
    let isEnabled: Bool
    let nodes: [XCUIElementSnapshot]
    let traversalCost: Duration
    init(_ type: XCUIElement.ElementType = .other, identifier: String = "", label: String = "",
         frame: CGRect = .zero, enabled: Bool = true, children: [XCUIElementSnapshot] = [],
         traversalCost: Duration = .zero) {
        self.elementType = type; self.identifier = identifier; self.label = label
        self.frame = frame; self.isEnabled = enabled; nodes = children; self.traversalCost = traversalCost
    }
    var children: [XCUIElementSnapshot] {
        ContinuousClock.elapsed += traversalCost
        return nodes
    }
}
@MainActor final class ShareWorld {
    var frames: [ShareFrame]
    var index = 0
    var polls = 0
    var taps = 0
    var captures = 0
    var current = ShareFrame()
    var reads: [String] = []
    var lateReady: Duration?
    init(_ frames: [ShareFrame]) { self.frames = frames }
    func snapshot() throws -> XCUIElementSnapshot {
        reads.append("snapshot"); polls += 1
        current = frames[min(index, frames.count - 1)]; index += 1
        if let lateReady, ContinuousClock.elapsed < lateReady { current.actions = 0 }
        ContinuousClock.elapsed += current.snapshotCost
        if current.snapshotFails { throw BatchTestFailure(message: "snapshot failed") }
        let f = current
        var children: [XCUIElementSnapshot] = []
        // First action is visited last by the LIFO traversal. A duplicate cannot
        // be missed by stopping once an earlier action and header were found.
        for _ in 0..<f.actions {
            children.append(XCUIElementSnapshot(f.type, identifier: f.identifier, label: f.label,
                                               frame: f.action, enabled: f.enabled, traversalCost: f.traversalCost))
        }
        children += (0..<f.fillers).map { _ in XCUIElementSnapshot(traversalCost: f.traversalCost) }
        for _ in 0..<f.headers {
            children.append(XCUIElementSnapshot(.navigationBar, identifier: "UIActivityContentView", label: f.headerLabel, frame: f.header))
        }
        if f.staticTextDecoy { children.append(XCUIElementSnapshot(.staticText, label: "Save to Files", frame: f.action)) }
        if let lateOverflow = f.lateOverflow {
            var tail = XCUIElementSnapshot(f.type, identifier: f.identifier, label: f.label, frame: f.action)
            if lateOverflow == "depth" {
                for _ in 0..<65 { tail = XCUIElementSnapshot(children: [tail]) }
            } else {
                tail = XCUIElementSnapshot(children: (0..<4_094).map { _ in XCUIElementSnapshot() })
            }
            children.insert(tail, at: 0)
        }
        if f.depth > 0 {
            for _ in 0..<f.depth { children = [XCUIElementSnapshot(children: children)] }
        }
        return XCUIElementSnapshot(.application, frame: f.bounds, children: children)
    }
}
@MainActor final class XCUIElement {
    enum ElementType: Int { case application = 2, navigationBar = 4, button = 9, cell = 75, staticText = 48, other = 1 }
    let world: ShareWorld
    let predicate: NSPredicate?
    init(_ world: ShareWorld, predicate: NSPredicate?) { self.world = world; self.predicate = predicate }
    var isHittable: Bool {
        world.reads.append("hittable")
        ContinuousClock.elapsed += world.current.hittableCost
        guard let predicate else { fatalError("Live query must constrain the snapshot identity") }
        let f = world.current
        return f.hittable && predicate.evaluate(with: ["elementType": (f.liveType ?? f.type).rawValue,
                                                        "identifier": f.liveIdentifier ?? f.identifier,
                                                        "label": f.liveLabel ?? f.label])
    }
    var isEnabled: Bool { fatalError("Forbidden extra live isEnabled RPC") }
    var frame: CGRect { fatalError("Forbidden extra live frame RPC") }
    var identifier: String { fatalError("Forbidden extra live identifier RPC") }
    var label: String { fatalError("Forbidden extra live label RPC") }
    var elementType: ElementType { fatalError("Forbidden extra live type RPC") }
    func tap() {
        precondition(ContinuousClock.elapsed < .seconds(40), "No late tap")
        precondition(world.polls >= 3, "No premature tap")
        world.taps += 1
    }
}
@MainActor final class XCUIElementQuery {
    let world: ShareWorld
    let predicate: NSPredicate?
    init(_ world: ShareWorld, predicate: NSPredicate? = nil) { self.world = world; self.predicate = predicate }
    var count: Int { fatalError("Forbidden extra live count RPC") }
    var element: XCUIElement { XCUIElement(world, predicate: predicate) }
    func matching(_ predicate: NSPredicate) -> XCUIElementQuery { XCUIElementQuery(world, predicate: predicate) }
}
@MainActor final class XCUIApplication {
    let world: ShareWorld
    init(_ world: ShareWorld) { self.world = world }
    func snapshot() throws -> XCUIElementSnapshot { try world.snapshot() }
    var frame: CGRect { fatalError("Forbidden extra live app frame RPC") }
}
@MainActor final class ShareHarness {
    let world: ShareWorld
    init(_ world: ShareWorld) { self.world = world }
    func capture(_ app: XCUIApplication, _ message: String, springboard: XCUIApplication? = nil, batchDiagnostic: Bool = false) { world.captures += 1 }
    // ACTUAL_WAIT
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
        otherIdentity.identifier = "system-action"; otherIdentity.type = .button
        var expectedPolls = 0
        var frames: [ShareFrame]
        var expectedHittable: Int?
        switch name {
        case "ready": frames = [ready]; expectedPolls = 3
        case "late-ready": invalid.actions = 0; frames = [invalid, invalid, ready]; expectedPolls = 5
        case "movement-resets": frames = [ready, ready, moved]; expectedPolls = 5
        case "tolerance-boundary": moved.action.origin.y = ready.action.origin.y + 0.5; frames = [ready, moved]; expectedPolls = 3
        case "tolerance-exceeded": moved.action.origin.y = ready.action.origin.y + 0.5001; frames = [ready, ready, moved]; expectedPolls = 5
        case "header-resets": moved = ready; moved.header.origin.y += 5; frames = [ready, ready, moved]; expectedPolls = 5
        case "header-label-resets": moved = ready; moved.headerLabel = "Different document"; frames = [ready, ready, moved]; expectedPolls = 5
        case "identity-resets": frames = [ready, ready, otherIdentity]; expectedPolls = 5
        case "unavailable-resets": invalid.actions = 0; frames = [ready, ready, invalid, ready]; expectedPolls = 6
        case "disabled-resets": invalid.enabled = false; frames = [ready, ready, invalid, ready]; expectedPolls = 6
        case "invalid-resets": invalid.action.size.width = 0; frames = [ready, ready, invalid, ready]; expectedPolls = 6
        case "moving": frames = (0..<512).map { i in var f = ready; f.action.origin.y += Double(i % 50); return f }
        case "absent": invalid.actions = 0; frames = [invalid]; expectedHittable = 0
        case "ambiguous": invalid.actions = 2; frames = [invalid]; expectedHittable = 0
        case "missing-header": invalid.headers = 0; frames = [invalid]; expectedHittable = 0
        case "ambiguous-header": invalid.headers = 2; frames = [invalid]; expectedHittable = 0
        case "disabled": invalid.enabled = false; frames = [invalid]; expectedHittable = 0
        case "hidden": invalid.hittable = false; frames = [invalid]
        case "zero-area": invalid.action.size.width = 0; frames = [invalid]; expectedHittable = 0
        case "offscreen": invalid.action.origin.x = -10; frames = [invalid]; expectedHittable = 0
        case "invalid-header": invalid.header.size.height = 0; frames = [invalid]; expectedHittable = 0
        case "nonfinite": invalid.action.origin.x = .infinity; frames = [invalid]; expectedHittable = 0
        case "invalid-bounds": invalid.bounds.size.width = .nan; frames = [invalid]; expectedHittable = 0
        case "snapshot-errors": invalid.snapshotFails = true; frames = [invalid]; expectedHittable = 0
        case "snapshot-error-resets": invalid.snapshotFails = true; frames = [ready, ready, invalid, ready]; expectedPolls = 6
        case "static-text-decoy": invalid.staticTextDecoy = true; frames = [invalid]; expectedPolls = 3
        case "static-text-only": invalid.type = .staticText; frames = [invalid]; expectedHittable = 0
        case "wrong-cell-id": invalid.identifier = "otherCell"; frames = [invalid]; expectedHittable = 0
        case "wrong-label": invalid.label = "Save to Files later"; frames = [invalid]; expectedHittable = 0
        case "live-identifier-mismatch": invalid.liveIdentifier = "newAction"; frames = [invalid]
        case "live-type-mismatch": invalid.liveType = .button; frames = [invalid]
        case "live-label-mismatch": invalid.liveLabel = "Copy"; frames = [invalid]
        case "late-duplicate": invalid.actions = 2; invalid.fillers = 200; frames = [invalid]; expectedHittable = 0
        case "node-limit": invalid.fillers = 4_094; frames = [invalid]; expectedHittable = 0
        case "node-limit-boundary": invalid.fillers = 4_093; frames = [invalid]; expectedPolls = 3
        case "depth-limit": invalid.depth = 65; frames = [invalid]; expectedHittable = 0
        case "late-depth-overflow": invalid.lateOverflow = "depth"; frames = [invalid]; expectedHittable = 0
        case "late-node-overflow": invalid.lateOverflow = "nodes"; frames = [invalid]; expectedHittable = 0
        case "late-snapshot": invalid.snapshotCost = .seconds(41); frames = [invalid]; expectedHittable = 0
        case "late-hittable": invalid.hittableCost = .seconds(41); frames = [invalid]; expectedHittable = 1
        case "late-third-snapshot": invalid.snapshotCost = .milliseconds(13_500); frames = [invalid]; expectedHittable = 2
        case "late-third-hittable": invalid.hittableCost = .milliseconds(13_500); frames = [invalid]; expectedHittable = 3
        case "exact-deadline": invalid.snapshotCost = .milliseconds(39_800); frames = [ready, ready, invalid]; expectedHittable = 2
        case "traversal-deadline": invalid.fillers = 3_000; invalid.traversalCost = .milliseconds(20); frames = [invalid]; expectedHittable = 0
        case "slow-late-ready": invalid.snapshotCost = .milliseconds(700); invalid.hittableCost = .milliseconds(700); frames = [invalid]; expectedPolls = -1
        default: fatalError("Unknown fixture")
        }
        let world = ShareWorld(frames)
        if name == "slow-late-ready" { world.lateReady = .seconds(30) }
        var failed = false
        do { try await ShareHarness(world).run() } catch { failed = true }
        let shouldFail = expectedPolls == 0
        precondition(failed == shouldFail, "Unexpected outcome: " + name)
        precondition(world.taps == (shouldFail ? 0 : 1), "Wrong tap count")
        precondition(world.captures == (shouldFail ? 1 : 0), "Failure capture changed")
        if expectedPolls > 0 { precondition(world.polls == expectedPolls, "Wrong convergence count") }
        if let expectedHittable { precondition(world.reads.filter { $0 == "hittable" }.count == expectedHittable) }
        precondition(world.reads.filter { $0 == "snapshot" }.count == world.polls)
        precondition(world.reads.filter { $0 == "hittable" }.count <= world.polls)
        precondition(world.reads.allSatisfy { $0 == "snapshot" || $0 == "hittable" })
        if name == "slow-late-ready" {
            precondition(!failed && ContinuousClock.elapsed > .seconds(30) && ContinuousClock.elapsed < .seconds(40))
            precondition(world.reads.filter { $0 == "hittable" }.count == 3)
        }
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
        wait_start = source.index('    private func wait(')
        wait_end = source.index('    private func check(', wait_start)
        path.write_text(SHARE_FIXTURE.replace('    // ACTUAL_HELPER', source[start:end])
                        .replace('    // ACTUAL_WAIT', source[wait_start:wait_end]))
        cls.binary = root / 'share-readiness-tests'
        result = subprocess.run(['/usr/bin/swiftc', '-parse-as-library', str(path), '-o', str(cls.binary)],
                                capture_output=True, text=True, timeout=60)
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

    def test_snapshot_completeness_identity_and_observation_deadline(self):
        for name in ['invalid-bounds', 'snapshot-errors', 'snapshot-error-resets',
                     'tolerance-boundary', 'tolerance-exceeded', 'late-depth-overflow', 'late-node-overflow',
                     'static-text-decoy', 'static-text-only', 'wrong-cell-id', 'wrong-label',
                     'live-identifier-mismatch', 'live-type-mismatch', 'live-label-mismatch',
                     'late-duplicate', 'node-limit', 'node-limit-boundary', 'depth-limit',
                     'late-snapshot', 'late-hittable', 'late-third-snapshot', 'late-third-hittable',
                     'exact-deadline', 'traversal-deadline', 'slow-late-ready']:
            with self.subTest(name=name):
                result = subprocess.run([str(self.binary), name], capture_output=True,
                                        text=True, check=True, timeout=5)
                self.assertEqual(result.stdout.strip(), 'PASS ' + name)

    def test_header_label_is_part_of_original_share_proof(self):
        result = subprocess.run([str(self.binary), 'header-label-resets'], capture_output=True,
                                text=True, check=True, timeout=5)
        self.assertEqual(result.stdout.strip(), 'PASS header-label-resets')

    def test_shared_export_path_retains_proof_before_bounded_navigation(self):
        source = SOURCE.read_text()
        start = source.index('    private func presentRecoverySave(')
        end = source.index('    private func waitForStableShareAction(', start)
        body = source[start:end]
        self.assertEqual(body.count('export.tap()'), 1)
        self.assertEqual(body.count('app.buttons["Export…"].tap()'), 1)
        self.assertEqual(body.count('.action.tap()'), 3)
        self.assertIn('retryNavigation: Bool = false', body)
        self.assertLess(body.index('try await waitForStableShareAction(saveToFiles, app: app)'),
                        body.index('try await openRecoveryFilesFromShare(saveToFiles, app: app, first: proof)'))


SHARE_TRANSITION_FIXTURE = r'''
import Foundation
import CoreGraphics
@MainActor enum ContinuousClock {
    struct Instant: Comparable {
        let time: Duration
        func advanced(by value: Duration) -> Instant { Instant(time: time + value) }
        func duration(to other: Instant) -> Duration { other.time - time }
        static func < (a: Instant, b: Instant) -> Bool { a.time < b.time }
    }
    static var elapsed: Duration = .zero
    static var now: Instant { Instant(time: elapsed) }
}
@MainActor enum Task {
    static var cancelled = false
    static func checkCancellation() throws { if cancelled { throw CancellationError() } }
    static func sleep(for value: Duration) async throws {
        if cancelled { throw CancellationError() }
        ContinuousClock.elapsed += value
    }
}
struct BatchTestFailure: Error { let message: String }
typealias Proof = (frames: [CGRect], identity: String, action: XCUIElement)
@MainActor final class World {
    let mode: String
    var initial: Proof { ([CGRect(x: 114, y: 304, width: 82, height: 138.3),
                           CGRect(x: 0, y: 78, width: 402, height: 95)], "75:actionGroupCell:Save to Files", XCUIElement(self)) }
    var taps: [Duration] = []
    var records: [String] = []
    var captures = 0
    var observations = 0
    var eligibleObservations = 0
    init(_ mode: String) { self.mode = mode }
    var navigation: Int {
        let now = ContinuousClock.elapsed
        if mode == "slow-navigation-count" { ContinuousClock.elapsed += .seconds(31); return 1 }
        if mode == "ambiguous-navigation" && now >= .seconds(1) && now < .seconds(2) { return 2 }
        if mode == "immediate" || mode == "slow-navigation-exists" { return 1 }
        if mode == "delayed-first" && now >= .seconds(10) { return 1 }
        if mode == "navigation-during-retry-proof" && eligibleObservations >= 3 { return 1 }
        if mode == "retry-opens" && taps.count == 2 { return 1 }
        return 0
    }
    func observation() -> Proof? {
        observations += 1
        if ContinuousClock.elapsed >= .seconds(15) { eligibleObservations += 1 }
        if mode == "slow-snapshot" { ContinuousClock.elapsed += .seconds(31) }
        if mode == "exact-deadline-snapshot" { ContinuousClock.elapsed = .seconds(30) }
        if mode == "exact-deadline-third" && eligibleObservations == 3 { ContinuousClock.elapsed = .seconds(30) }
        if mode == "slow-third-proof" && eligibleObservations == 3 { ContinuousClock.elapsed += .seconds(31) }
        if ["missing-share", "ambiguous-share", "failed-snapshot"].contains(mode) && observations == 2 { return nil }
        if mode == "changed-geometry" && observations == 2 {
            var changed = initial; changed.frames[0].origin.y += 1; return changed
        }
        if mode == "changed-header" && observations == 2 {
            var changed = initial; changed.frames[1].size.height += 1; return changed
        }
        if mode == "changed-identity" && observations == 2 { return (initial.frames, "different", initial.action) }
        if mode == "changed-header-label" && observations == 2 { return (initial.frames, initial.identity + "Different document", initial.action) }
        return initial
    }
}
@MainActor final class XCUIElement {
    let world: World
    init(_ world: World) { self.world = world }
    var exists: Bool {
        if world.mode == "slow-navigation-exists" { ContinuousClock.elapsed += .seconds(31) }
        return true
    }
    func tap() {
        world.taps.append(ContinuousClock.elapsed)
        if world.mode == "slow-first-tap" { ContinuousClock.elapsed += .seconds(31) }
    }
}
@MainActor final class XCUIElementQuery {
    let world: World
    let kind: String
    init(_ world: World, kind: String = "actions") { self.world = world; self.kind = kind }
    func matching(identifier: String) -> XCUIElementQuery { self }
    var element: XCUIElement { XCUIElement(world) }
    var count: Int {
        if kind == "navigation" { return world.navigation }
        if kind == "picker" && world.mode == "partial-picker"
            && ContinuousClock.elapsed >= .seconds(1) && ContinuousClock.elapsed < .seconds(2) { return 1 }
        return 0
    }
}
@MainActor final class XCUIApplication {
    enum State { case runningForeground, background }
    let world: World
    init(_ world: World) { self.world = world }
    var state: State {
        if world.mode == "slow-final-state" && world.eligibleObservations >= 3 { ContinuousClock.elapsed += .seconds(31) }
        if world.mode == "background" && ContinuousClock.elapsed >= .seconds(1)
            && ContinuousClock.elapsed < .seconds(2) { return .background }
        return .runningForeground
    }
    var navigationBars: XCUIElementQuery { XCUIElementQuery(world, kind: "navigation") }
    var otherElements: XCUIElementQuery { XCUIElementQuery(world, kind: "picker") }
}
@MainActor final class Harness {
    let world: World
    init(_ world: World) { self.world = world }
    func recordRecoveryShareTransition(_ message: String) {
        world.records.append(message)
        if world.mode == "cancel-before-retry" && message.contains("dispatch intent 2") { Task.cancelled = true }
        if world.mode == "slow-dispatch-record" && message.contains("dispatch intent 2") {
            ContinuousClock.elapsed += .seconds(31)
        }
    }
    func shareActionObservation(_ actions: XCUIElementQuery, app: XCUIApplication,
                                before deadline: ContinuousClock.Instant) -> Proof? { world.observation() }
    func capture(_ app: XCUIApplication, _ message: String, batchDiagnostic: Bool) { world.captures += 1 }
    // ACTUAL_TRANSITION
    func run() async throws {
        try await openRecoveryFilesFromShare(XCUIElementQuery(world), app: XCUIApplication(world), first: world.initial)
    }
}
@main struct Main {
    @MainActor static func main() async {
        let mode = CommandLine.arguments[1]
        let world = World(mode)
        var failed = false
        var cancelled = false
        Task.cancelled = mode == "cancel-before-first"
        do { try await Harness(world).run() } catch { failed = true; cancelled = error is CancellationError }
        precondition(cancelled == mode.hasPrefix("cancel-"))
        let succeeds = ["immediate", "delayed-first", "retry-opens", "navigation-during-retry-proof"].contains(mode)
        precondition(failed != succeeds, "Wrong result for " + mode)
        let twoTaps = ["retry-opens", "retry-still-pending"].contains(mode)
        precondition(world.taps.count == (mode == "cancel-before-first" ? 0 : (twoTaps ? 2 : 1)), "Wrong tap count for " + mode)
        precondition(world.taps.allSatisfy { $0 < .seconds(30) }, "Late tap")
        if twoTaps { precondition(world.taps[1] >= .seconds(15) && world.eligibleObservations >= 3) }
        if mode == "retry-still-pending" { precondition(ContinuousClock.elapsed >= .seconds(30) && ContinuousClock.elapsed < .seconds(31)) }
        if ["missing-share", "ambiguous-share", "failed-snapshot", "changed-geometry", "changed-header",
            "changed-identity", "changed-header-label", "background", "partial-picker", "ambiguous-navigation"].contains(mode) {
            precondition(world.records.filter { $0.contains("retry disabled:") }.count == 1)
        }
        precondition(world.captures == (succeeds || cancelled ? 0 : 1))
        print("PASS " + mode)
    }
}
'''


class ShareTransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        source = SOURCE.read_text()
        start = source.index('    private func openRecoveryFilesFromShare(')
        end = source.index('    private func waitForStableShareAction(', start)
        path = Path(cls.directory.name) / 'ShareTransition.swift'
        path.write_text(SHARE_TRANSITION_FIXTURE.replace('    // ACTUAL_TRANSITION', source[start:end]))
        cls.binary = Path(cls.directory.name) / 'share-transition-tests'
        result = subprocess.run(['/usr/bin/swiftc', '-parse-as-library', str(path), '-o', str(cls.binary)],
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stderr)

    def test_one_navigation_retry_requires_unchanged_share_and_original_deadline(self):
        for name in ['immediate', 'delayed-first', 'retry-opens', 'retry-still-pending',
                     'navigation-during-retry-proof', 'missing-share', 'ambiguous-share',
                     'failed-snapshot', 'changed-geometry', 'changed-header', 'changed-identity', 'changed-header-label',
                     'background', 'partial-picker', 'ambiguous-navigation', 'slow-snapshot',
                     'slow-third-proof', 'slow-navigation-count', 'slow-navigation-exists', 'slow-dispatch-record',
                     'slow-first-tap', 'exact-deadline-snapshot', 'exact-deadline-third',
                     'slow-final-state', 'cancel-before-first', 'cancel-before-retry']:
            with self.subTest(name=name):
                result = subprocess.run([str(self.binary), name], capture_output=True,
                                        text=True, check=True, timeout=5)
                self.assertEqual(result.stdout.strip(), 'PASS ' + name)

    def test_retry_does_not_repeat_export_or_destination_save(self):
        source = SOURCE.read_text()
        start = source.index('    private func openRecoveryFilesFromShare(')
        end = source.index('    private func waitForStableShareAction(', start)
        transition = source[start:end]
        self.assertEqual(transition.count('.action.tap()'), 2)
        for forbidden in ['Export…', 'export.tap()', 'save.tap()', 'launch()', 'terminate()']:
            self.assertNotIn(forbidden, transition)
        start = source.index('    func testRecoveryExportFullBackupThroughFiles(')
        end = source.index('    func testRecoveryRestoreIntoEmptyFreeLibraryAndOpenOriginal(', start)
        self.assertEqual(source[start:end].count('save.tap()'), 1)
        self.assertIn('presentRecoverySave(app, retryNavigation: true)', source[start:end])
        self.assertEqual(source.count('presentRecoverySave(app, retryNavigation: true)'), 1)

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
                                capture_output=True, text=True, timeout=60)
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
        end = source.index('\n    private func ', start + 1)
        root = Path(cls.directory.name)
        path = root / 'SelectionDiagnostic.swift'
        path.write_text(SELECTION_DIAGNOSTIC_FIXTURE.replace('    // ACTUAL_HELPER', source[start:end]))
        cls.binary = root / 'selection-diagnostic-tests'
        result = subprocess.run(['/usr/bin/swiftc', '-parse-as-library', str(path), '-o', str(cls.binary)],
                                capture_output=True, text=True, timeout=60)
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
    var enabledReads = 0
    var hittableReads = 0
    var snapshots = 0
    var navigationQueries = 0
    var liveRoot: XCUIElementSnapshot?
    var identifierChanged = false
    var rejectedTapResolutions = 0
    var title: String { name.hasPrefix("russian-") ? "Настройки" : "Settings" }
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
        let initialIdentifier = name.contains("empty-id") && name != "nonempty-id-changed" && taps == 0 ? "" : "gearshape"
        let leaf = XCUIElementSnapshot(.button, title, initialIdentifier, frame)
        leaf.isEnabled = name != "disabled-snapshot"
        leaf.isSelected = taps > 0 && name != "unselected"
        if name == "single-button" || (name.contains("empty-id") && !name.contains("pair")) || name == "nonempty-id-changed" { root.storedChildren = [leaf] }
        else {
            let parent = XCUIElementSnapshot(.button, title, initialIdentifier, frame)
            parent.storedChildren = [leaf]; root.storedChildren = [parent]
        }
        if name == "ambiguous-tab" { root.storedChildren.append(XCUIElementSnapshot(.button, "Settings", "gearshape", frame)) }
        if taps > 0 {
            let nav = XCUIElementSnapshot(.navigationBar, "", name == "wrong-navigation" ? "Trips" : title,
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
        liveRoot = root
        return root
    }
    func liveButtons() -> [XCUIElementSnapshot] {
        func flatten(_ node: XCUIElementSnapshot) -> [XCUIElementSnapshot] {
            (node.elementType == .button ? [node] : []) + node.storedChildren.flatMap(flatten)
        }
        var nodes = liveRoot.map(flatten) ?? []
        if name == "empty-id-live-duplicate", let first = nodes.first {
            nodes.append(XCUIElementSnapshot(.button, title, "another-action", first.frame))
        }
        return nodes
    }
    func identifier(_ node: XCUIElementSnapshot) -> String {
        if name == "nonempty-id-changed" { return "another-identifier" }
        if name == "empty-id-before-hit" || (name.contains("before-tap") && identifierChanged) {
            return "gearshape"
        }
        return node.identifier
    }
}
@MainActor final class XCUIElement {
    let query: XCUIElementQuery
    var world: World { query.world }
    init(_ query: XCUIElementQuery) { self.query = query }
    var isEnabled: Bool {
        world.enabledReads += 1
        if world.name == "redundant-enabled-cost" { ContinuousClock.elapsed += .seconds(5) }
        return query.nodes().count == 1 && query.nodes()[0].isEnabled
    }
    var isHittable: Bool {
        world.hittableReads += 1
        if world.name == "late-live-hittable" { ContinuousClock.elapsed += .seconds(5) }
        guard query.nodes().count == 1, world.name != "unhittable-tab" else { return false }
        if world.name.contains("before-tap") { world.identifierChanged = true }
        return true
    }
    // A repeated live navigation query must still be caught by the fixture.
    var exists: Bool {
        world.navigationQueries += 1
        ContinuousClock.elapsed += .milliseconds(8200)
        return true
    }
    func tap() {
        // Model .element's unique live resolution: no action is delivered
        // if the query has become empty or ambiguous after readiness.
        guard query.nodes().count == 1 else { world.rejectedTapResolutions += 1; return }
        world.taps += 1; world.tappedAt = ContinuousClock.elapsed
    }
}
@MainActor final class XCUIElementQuery {
    let world: World
    let nodes: () -> [XCUIElementSnapshot]
    init(_ world: World, nodes: (() -> [XCUIElementSnapshot])? = nil) {
        self.world = world; self.nodes = nodes ?? { world.liveButtons() }
    }
    func matching(_ predicate: NSPredicate) -> XCUIElementQuery {
        XCUIElementQuery(world) {
            self.nodes().filter { predicate.evaluate(with: ["label": $0.label, "identifier": self.world.identifier($0)]) }
        }
    }
    func children(matching type: ElementType) -> XCUIElementQuery {
        XCUIElementQuery(world) { self.nodes().flatMap(\.storedChildren).filter { $0.elementType == type } }
    }
    var element: XCUIElement {
        // Retain an unavoidable initial identity-resolution cost in this scenario.
        if world.name == "redundant-enabled-cost" { ContinuousClock.elapsed += .milliseconds(500) }
        if world.name == "late-identity-resolution" { ContinuousClock.elapsed += .seconds(5) }
        return XCUIElement(self)
    }
    subscript(_ identifier: String) -> XCUIElement { XCUIElement(self) }
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
        try await selectTab(app.world.title, navigationTitle: app.world.title, failure: "Settings did not open", in: app)
    }
}
@main struct Main {
    @MainActor static func main() async {
        let name = CommandLine.arguments[1], world = World(CommandLine.arguments[1])
        let success = ["redundant-enabled-cost", "ready", "single-button", "label-navigation", "empty-id-stable", "empty-id-before-hit", "empty-id-before-tap", "empty-id-pair-before-tap", "russian-empty-id-before-tap"].contains(name)
        let beforeTapFailure = ["disabled-snapshot", "late-live-hittable", "late-identity-resolution", "ambiguous-tab", "unhittable-tab", "empty-id-live-duplicate", "nonempty-id-changed"].contains(name)
        var failed = false
        do { try await Harness().run(XCUIApplication(world)) } catch { failed = true }
        precondition(failed != success)
        precondition(world.taps == (beforeTapFailure ? 0 : 1))
        precondition(world.enabledReads == 0)
        if name == "redundant-enabled-cost" || name == "late-live-hittable" { precondition(world.hittableReads == 1) }
        if name == "disabled-snapshot" || name == "late-identity-resolution" { precondition(world.hittableReads == 0) }
        precondition(world.navigationQueries == 0)
        precondition(world.rejectedTapResolutions == 0)
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
                                capture_output=True, text=True, timeout=60)
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


    def test_live_query_keeps_unique_tab_when_initial_identifier_is_empty(self):
        for name in ['empty-id-stable', 'empty-id-before-hit', 'empty-id-before-tap',
                     'empty-id-pair-before-tap', 'russian-empty-id-before-tap',
                     'empty-id-live-duplicate', 'nonempty-id-changed']:
            with self.subTest(name=name):
                result = subprocess.run([str(self.binary), name], capture_output=True,
                                        text=True, check=True, timeout=5)
                self.assertEqual(result.stdout.strip(), 'PASS ' + name)

    def test_snapshot_enabled_and_one_live_hit_check_preserve_original_deadline(self):
        for name in ['redundant-enabled-cost', 'disabled-snapshot',
                     'late-live-hittable', 'late-identity-resolution']:
            with self.subTest(name=name):
                result = subprocess.run([str(self.binary), name], capture_output=True,
                                        text=True, check=True, timeout=5)
                self.assertEqual(result.stdout.strip(), 'PASS ' + name)


UI = SOURCE.read_text()

RESTORE_NAVIGATION_SWIFT = r'''
import Foundation
import CoreGraphics
enum Kind { case application, window, other, collectionView, navigationBar, keyboard, cell, button, textView, textField, staticText, menu, menuItem, alert, sheet, popover }
@MainActor final class XCUIElementSnapshot {
    var elementType: Kind; var identifier: String; var label: String; var frame: CGRect
    var children: [XCUIElementSnapshot] = []; var isEnabled = true
    init(_ type: Kind, _ id: String = "", _ label: String = "", _ frame: CGRect = .zero) {
        elementType = type; identifier = id; self.label = label; self.frame = frame
    }
}
@MainActor final class Tree {
    let cell: XCUIElementSnapshot
    let title: XCUIElementSnapshot
    let grid = XCUIElementSnapshot(.collectionView, "File View", "", CGRect(x: 0, y: 72, width: 402, height: 802))
    let nav = XCUIElementSnapshot(.navigationBar, "FullDocumentManagerViewControllerNavigationBar", "", CGRect(x: 0, y: 88, width: 402, height: 114))
    let root: XCUIElementSnapshot
    let picker = XCUIElementSnapshot(.other, "Browse View (Picker)", "", CGRect(x: 0, y: 72, width: 402, height: 802))
    let window = XCUIElementSnapshot(.window, "", "", CGRect(x: 0, y: 0, width: 402, height: 874))
    let app = XCUIElementSnapshot(.application)
    init(_ folder: String, _ local: String = "On My iPhone") {
        cell = XCUIElementSnapshot(.cell, folder + ", Folder", folder + ", 1 item", CGRect(x: 10, y: 212, width: 122, height: 189.7))
        title = XCUIElementSnapshot(.staticText, "", local, CGRect(x: 146, y: 99.7, width: 109.7, height: 20.7))
        root = XCUIElementSnapshot(.other, "DOC.browsingRoot Source: com.apple.FileProvider.LocalStorage, Title: " + local, "", picker.frame)
        grid.children = [cell]; nav.children = [title]; root.children = [nav, grid]
        picker.children = [root]; app.children = [window]
    }
    func mutate(_ shape: String) {
        switch shape {
        case "duplicate-cell": grid.children.append(cell)
        case "duplicate-title": nav.children.append(title)
        case "duplicate-grid": root.children.append(grid)
        case "duplicate-root": picker.children.append(root)
        case "foreign-root": root.identifier = "DOC.browsingRoot Source: com.apple.CloudDocs, Title: On My iPhone"
        case "extra-root": picker.children.append(XCUIElementSnapshot(.other, "DOC.browsingRoot Source: foreign"))
        case "outside-root": root.children = [nav]; picker.children.append(grid)
        case "wrong-cell": cell.identifier = "foreign, Folder"
        case "wrong-label": cell.label = "foreign, 1 item"
        case "changed-contents": cell.label = cell.label.replacingOccurrences(of: "1 item", with: "2 items")
        case "disabled": cell.isEnabled = false
        case "wrong-title": title.label = "foreign"
        case "frame": cell.frame.origin.x += 1
        case "root-frame": root.frame.size.width -= 1
        case "window-frame": window.frame.size.width -= 1
        case "outside": cell.frame.origin.y = 900
        case "empty": cell.frame.size.width = 0
        case "nan": cell.frame.origin.x = .nan
        case "no-window": app.children = []
        case "conflicting-window": app.children.append(XCUIElementSnapshot(.window, "", "", CGRect(x: 0, y: 0, width: 100, height: 100)))
        case "editor": window.children.append(XCUIElementSnapshot(.other, "DOC.inlineRenameField"))
        case "introduction": window.children.append(XCUIElementSnapshot(.other, "UIContinuousPathIntroductionView"))
        case "keyboard": window.children.append(XCUIElementSnapshot(.keyboard))
        case "menu": window.children.append(XCUIElementSnapshot(.menu))
        case "alert": window.children.append(XCUIElementSnapshot(.alert))
        case "sheet": window.children.append(XCUIElementSnapshot(.sheet))
        case "popover": window.children.append(XCUIElementSnapshot(.popover))
        case "text-field": window.children.append(XCUIElementSnapshot(.textField))
        case "over-count": picker.children += (0..<4097).map { _ in XCUIElementSnapshot(.other) }
        case "over-depth":
            var node = root
            for _ in 0..<98 { let child = XCUIElementSnapshot(.other); node.children.append(child); node = child }
        default: break
        }
    }
}
struct Duration { let value: Double; static func seconds(_ x: Double) -> Self { Self(value: x) }; static func milliseconds(_ x: Double) -> Self { Self(value: x / 1000) } }
struct ContinuousClock: Comparable {
    let value: Double
    @MainActor static var now: Self { Self(value: State.time) }
    func advanced(by duration: Duration) -> Self { Self(value: value + duration.value) }
    static func < (a: Self, b: Self) -> Bool { a.value < b.value }
}
enum Task { @MainActor static func sleep(for duration: Duration) async throws { State.time += duration.value } }
enum Idiom { case phone, pad }
struct UIDevice { static var current: Self { Self() }; var userInterfaceIdiom: Idiom { .phone } }
struct Failure: Error {}
@MainActor enum State {
    static var mode = "", time = 100.0, taps = [Double](), samples = 0, destination = false, destinations = 0
    static var stages = [(String, Double)](), oldWaits = 0
    static let folder = "TripDocket-Recovery-5862688f-b5ba-58df-9831-cb8796c62d6f"
    static func stage(_ name: String) { stages.append((name, time)) }
}
enum AppState { case runningForeground, background }
@MainActor final class Element {
    let kind: String
    init(_ kind: String) { self.kind = kind }
    var cells: Query { Query("cell") }; var otherElements: Query { Query("root") }; var collectionViews: Query { Query("grid") }
    var exists: Bool { State.mode != "live-missing" }
    var isEnabled: Bool { State.mode != "live-disabled" }
    var isHittable: Bool {
        if State.mode == "destination-during-live" { State.destination = true }
        if State.mode == "expiry-during-live" { State.time = 116 }
        return State.mode != "live-hidden"
    }
    var frame: CGRect {
        let tree = Tree(State.folder)
        if kind == "cell" && State.mode == "live-frame" { tree.cell.frame.origin.x += 1 }
        return ["picker": tree.picker.frame, "root": tree.root.frame, "grid": tree.grid.frame,
                "nav": tree.nav.frame, "cell": tree.cell.frame][kind]!
    }
    func tap() {
        State.taps.append(State.time)
        if State.mode == "first-opens" || State.taps.count == 2 && State.mode != "persistent" { State.destination = true }
    }
}
@MainActor struct Query {
    let kind: String
    init(_ kind: String) { self.kind = kind }
    func matching(identifier: String) -> Self { self }
    var element: Element { Element(kind) }
    var count: Int {
        if kind == "cell" && State.mode == "live-duplicate" { return 2 }
        if kind == "root" && State.mode == "live-root" { return 0 }
        return 1
    }
}
@MainActor final class App { var state: AppState { State.mode == "background" ? .background : .runningForeground } }
@MainActor final class Harness {
    // ACTUAL_HELPER
    func nativeFolderSnapshots(_ app: App) throws -> (picker: XCUIElementSnapshot, application: XCUIElementSnapshot) {
        State.stage("snapshot"); State.samples += 1
        let tree = Tree(State.folder)
        let n = State.samples, mode = State.mode
        if mode == "snapshot-error" { throw Failure() }
        if mode == "destination-during-final" && n == 3 { State.destination = true }
        if mode == "expiry-during-first" && n == 1 || mode == "expiry-during-final" && n == 3 { State.time = 116 }
        if mode.hasPrefix("reject-") { tree.mutate(String(mode.dropFirst(7))) }
        if mode.hasPrefix("second-") && n == 2 { tree.mutate(String(mode.dropFirst(7))) }
        if mode.hasPrefix("final-") && n == 3 { tree.mutate(String(mode.dropFirst(6))) }
        return (tree.picker, tree.app)
    }
    func isRecoveryFolder(_ value: String, navigation: Element) -> Bool { State.mode != "live-title" }
    func failure(_ message: String, app: App) -> Failure { Failure() }
    func wait(_ message: String, app: App, condition: () -> Bool) async throws {
        State.oldWaits += 1
        guard condition() else { throw Failure() }
    }
    func run(_ retryRecoveryFolderEntry: Bool, folder: String) async throws -> Element {
        let app = App(), picker = Element("picker"), directory = Element("cell"), navigation = Element("nav")
        let navigations = Query("nav"), pickers = Query("picker")
        let atDestination = {
            State.stage("destination"); State.destinations += 1
            if State.mode == "already-destination" { return true }
            if State.mode == "expiry-during-destination" && State.destinations == 2 { State.time = 116 }
            return State.destination
        }
        // ACTUAL_LOOP
    }
    static func proof(_ shape: String, folder: String, local: String) -> Bool {
        let tree = Tree(folder, local); tree.mutate(shape)
        return recoveryFolderParentGeometry(in: tree.picker, applicationSnapshot: tree.app, folder: folder, localTitle: local) != nil
    }
}
@main struct Main {
    @MainActor static func main() async {
        let args = Array(CommandLine.arguments.dropFirst())
        if args[0] == "proof" { print(Harness.proof(args[1], folder: args[2], local: args[3])); return }
        State.mode = args[0]
        var result = "passed"
        do { _ = try await Harness().run(args[0] != "disabled", folder: args.count > 1 ? args[1] : State.folder) }
        catch { result = "failed" }
        let lateStages = State.stages.filter { $0.1 >= 115 }.count
        let object: [String: Any] = ["result": result, "taps": State.taps, "samples": State.samples,
                                   "now": State.time, "lateStages": lateStages, "oldWaits": State.oldWaits]
        print(String(data: try! JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]), encoding: .utf8)!)
    }
}
'''


class RestoreFolderNavigation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix='restore-folder-navigation-')
        cls.addClassCleanup(cls.scratch.cleanup)
        path = Path(cls.scratch.name)
        start = UI.index('    @MainActor\n    private static func recoveryFolderParentGeometry(')
        helper = UI[start:UI.index('    private func openLocalFilesFolder(', start)]
        start = UI.index('        if !atDestination() { directory.tap() }', UI.index('    private func openLocalFilesFolder('))
        end = UI.index('\n    }\n', start)
        loop = UI[start:end]
        swift = path / 'Navigation.swift'
        swift.write_text(RESTORE_NAVIGATION_SWIFT.replace('    // ACTUAL_HELPER', helper).replace('        // ACTUAL_LOOP', loop))
        cls.binary = path / 'navigation'
        result = subprocess.run(['/usr/bin/swiftc', '-swift-version', '6', '-strict-concurrency=complete',
                                 '-parse-as-library', str(swift), '-o', str(cls.binary)],
                                capture_output=True, text=True, timeout=60)
        if result.returncode: raise AssertionError(result.stdout + result.stderr)

    def probe(self, *args):
        result = subprocess.run([str(self.binary), *args], check=True, capture_output=True, text=True, timeout=5)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_persistent_parent_permits_only_one_second_tap(self):
        result = self.probe('persistent')
        self.assertEqual(result['result'], 'failed')
        self.assertEqual(len(result['taps']), 2)
        self.assertEqual(result['samples'], 3)
        self.assertLess(result['taps'][1], 115)
        self.assertLess(result['now'], 115.11)
        self.assertEqual(result['lateStages'], 0)

    def test_retry_can_reach_destination(self):
        result = self.probe('opens-on-retry')
        self.assertEqual((result['result'], len(result['taps']), result['samples']), ('passed', 2, 3))

    def test_destination_first_at_every_boundary_prevents_second_tap(self):
        for mode, count in [('already-destination', 0), ('first-opens', 1),
                            ('destination-during-final', 1), ('destination-during-live', 1)]:
            with self.subTest(mode=mode):
                result = self.probe(mode)
                self.assertEqual(result['result'], 'passed')
                self.assertEqual(len(result['taps']), count)

    def test_changed_second_state_never_rearms_on_later_valid_state(self):
        for shape in ['frame', 'root-frame', 'window-frame', 'changed-contents', 'duplicate-cell', 'editor', 'menu', 'foreign-root']:
            with self.subTest(shape=shape):
                result = self.probe('second-' + shape)
                self.assertEqual((len(result['taps']), result['samples'], result['result']), (1, 2, 'failed'))

    def test_final_snapshot_or_live_guard_changes_forbid_retry(self):
        for mode in ['final-frame', 'final-root-frame', 'final-editor', 'final-menu', 'final-foreign-root',
                     'live-root', 'live-title', 'live-frame', 'live-duplicate', 'live-disabled', 'live-hidden',
                     'live-missing', 'background']:
            with self.subTest(mode=mode): self.assertEqual(len(self.probe(mode)['taps']), 1)

    def test_expiry_during_any_observation_starts_no_later_stage_or_tap(self):
        for mode in ['expiry-during-destination', 'expiry-during-first', 'expiry-during-final', 'expiry-during-live']:
            with self.subTest(mode=mode):
                result = self.probe(mode)
                self.assertEqual((result['result'], len(result['taps']), result['lateStages']), ('failed', 1, 0))

    def test_invalid_or_failed_first_snapshot_disables_retry(self):
        for mode in ['snapshot-error', 'reject-duplicate-cell', 'reject-alert', 'reject-sheet', 'reject-popover',
                     'reject-editor', 'reject-keyboard', 'reject-introduction', 'reject-text-field']:
            with self.subTest(mode=mode):
                result = self.probe(mode)
                self.assertEqual((len(result['taps']), result['samples']), (1, 1))

    def test_real_proof_rejects_structural_and_geometry_ambiguity(self):
        folder = 'TripDocket-Recovery-5862688f-b5ba-58df-9831-cb8796c62d6f'
        for shape in ['duplicate-cell', 'duplicate-title', 'duplicate-grid', 'duplicate-root', 'extra-root',
                      'foreign-root', 'outside-root', 'wrong-cell', 'wrong-label', 'changed-contents', 'disabled', 'wrong-title',
                      'outside', 'empty', 'nan', 'no-window', 'conflicting-window', 'over-count', 'over-depth']:
            with self.subTest(shape=shape): self.assertFalse(self.probe('proof', shape, folder, 'On My iPhone'))

    def test_proof_requires_canonical_owned_name_and_explicit_local_title(self):
        folder = 'TripDocket-Recovery-5862688f-b5ba-58df-9831-cb8796c62d6f'
        for local in ['On My iPhone', 'On My iPad']:
            self.assertTrue(self.probe('proof', 'exact', folder, local))
        for bad in [folder.upper(), folder + '-extra', 'TripDocket-Recovery-any', 'Documents',
                    folder.replace('Recovery', 'Batch-QA')]:
            self.assertFalse(self.probe('proof', 'exact', bad, 'On My iPhone'))
        self.assertFalse(self.probe('proof', 'exact', folder, 'iCloud Drive'))

    def test_default_path_retains_original_single_tap_wait_without_sampling(self):
        result = self.probe('disabled')
        self.assertEqual((len(result['taps']), result['samples'], result['oldWaits']), (1, 0, 1))

    def test_only_restore_explicitly_opts_in_and_original_actions_remain(self):
        self.assertEqual(UI.count('retryRecoveryFolderEntry: true'), 1)
        restore = UI[UI.index('    func testRecoveryRestoreIntoEmptyFreeLibraryAndOpenOriginal()'):UI.index('    private func isRecoveryFolder(')]
        self.assertIn('openLocalFilesFolder(recoveryFolder, app: app, retryRecoveryFolderEntry: true)', restore)
        self.assertIn('let recoveryFolder = try recoveryConfiguration(phase: "restore")', restore)
        self.assertIn('retryRecoveryFolderEntry: Bool = false', UI)




RECOVERY_PERSON_INTRODUCTION = r'''
import Foundation
import CoreGraphics
struct NSPredicate {
    let value: String
    init(format: String, _ value: String) { precondition(format == "label == %@"); self.value = value }
}
struct Rejected: Error {}
struct Cancelled: Error {}
@MainActor enum Task {
    static var cancelled = false
    static func checkCancellation() throws { if cancelled { throw Cancelled() } }
}
@MainActor final class PersonWorld {
    var introduction = 1, alerts = 1, matchingAlerts = 1, fields = 1, matchingFields = 1
    var explanations = 1, buttons = 1
    var value = "Recovery Sentinel"
    var fieldEnabled = true, explanationHittable = true, buttonEnabled = true, buttonHittable = true
    var foreground = true
    var taps = 0, captures = 0, waits = 0, elementTaps = 0
    var rootFrame = CGRect(x: 0, y: 0, width: 402, height: 874)
    var introFrame = CGRect(x: 0, y: 539, width: 402, height: 335)
    var buttonFrame = CGRect(x: 89, y: 819, width: 224, height: 21)
    var appAnchor = false, point = CGPoint.zero
    let mode: String
    init(_ mode: String) {
        self.mode = mode
        switch mode {
        case "absent", "late": introduction = 0
        case "duplicate-intro": introduction = 2
        case "extra-alert": alerts = 2
        case "wrong-alert": matchingAlerts = 0
        case "extra-field": fields = 2
        case "wrong-field": matchingFields = 0
        case "wrong-value": value = "Foreign person"
        case "partial-value": value = "Recovery"
        case "disabled-field": fieldEnabled = false
        case "missing-explanation": explanations = 0
        case "duplicate-explanation": explanations = 2
        case "hidden-explanation": explanationHittable = false
        case "missing-continue": buttons = 0
        case "duplicate-continue": buttons = 2
        case "disabled-continue": buttonEnabled = false
        case "hidden-continue": buttonHittable = false
        case "background": foreground = false
        case "cancelled": Task.cancelled = true
        case "empty-button": buttonFrame.size.width = 0
        case "nan-button": buttonFrame.origin.x = .nan
        case "infinite-intro": introFrame.size.height = .infinity
        case "button-outside-intro": buttonFrame.origin.y = 500
        case "intro-outside-app": introFrame.size.height = 400
        case "empty-root": rootFrame.size.height = 0
        case "invalid-root": rootFrame.origin.x = .infinity
        case "app-origin":
            rootFrame = rootFrame.offsetBy(dx: 101, dy: 203)
            introFrame = introFrame.offsetBy(dx: 101, dy: 203)
            buttonFrame = buttonFrame.offsetBy(dx: 101, dy: 203)
        default: break
        }
    }
}
@MainActor final class XCUIApplication {
    enum State { case runningForeground, runningBackground }
    let world: PersonWorld
    init(_ world: PersonWorld) { self.world = world }
    var state: State { world.foreground ? .runningForeground : .runningBackground }
    var otherElements: PersonQuery { PersonQuery(world, "other") }
    var alerts: PersonQuery { PersonQuery(world, "alerts") }
    var frame: CGRect { world.rootFrame }
    func coordinate(withNormalizedOffset offset: CGVector) -> PersonCoordinate {
        precondition(offset == .zero)
        world.appAnchor = true
        return PersonCoordinate(world)
    }
}
@MainActor final class PersonCoordinate {
    let world: PersonWorld
    init(_ world: PersonWorld) { self.world = world }
    func withOffset(_ offset: CGVector) -> PersonCoordinate {
        world.point = CGPoint(x: offset.dx, y: offset.dy)
        return self
    }
    func tap() {
        precondition(world.appAnchor && world.elementTaps == 0)
        precondition(world.point == CGPoint(x: world.buttonFrame.midX - world.rootFrame.minX,
                                          y: world.buttonFrame.midY - world.rootFrame.minY))
        world.taps += 1
        if world.mode != "stays-open" { world.introduction = 0 }
        if world.mode == "changed-after-tap" { world.value = "Foreign person" }
        if world.mode == "form-dismissed" { world.alerts = 0 }
    }
}
@MainActor final class PersonQuery {
    let world: PersonWorld, kind: String
    init(_ world: PersonWorld, _ kind: String) { self.world = world; self.kind = kind }
    var count: Int {
        switch kind {
        case "intro": return world.introduction
        case "alerts": return world.alerts
        case "alert": return world.matchingAlerts
        case "fields": return world.fields
        case "field": return world.matchingFields
        case "explanation": return world.explanations
        case "continue": return world.buttons
        default: preconditionFailure("Unscoped query")
        }
    }
    var element: PersonElement { PersonElement(world, kind) }
    func matching(identifier: String) -> PersonQuery {
        switch (kind, identifier) {
        case ("other", "UIContinuousPathIntroductionView"): return PersonQuery(world, "intro")
        case ("alerts", "Add a person"): return PersonQuery(world, "alert")
        case ("fields", "Name or nickname"): return PersonQuery(world, "field")
        default: preconditionFailure("Unexpected identity")
        }
    }
    func matching(_ predicate: NSPredicate) -> PersonQuery {
        if kind == "texts" {
            precondition(predicate.value == "Speed up your typing by sliding your finger across the letters to compose a word.")
            return PersonQuery(world, "explanation")
        }
        precondition(kind == "buttons" && predicate.value == "Continue")
        return PersonQuery(world, "continue")
    }
}
@MainActor final class PersonElement {
    let world: PersonWorld, kind: String
    init(_ world: PersonWorld, _ kind: String) { self.world = world; self.kind = kind }
    var textFields: PersonQuery { precondition(kind == "alert"); return PersonQuery(world, "fields") }
    var staticTexts: PersonQuery { precondition(kind == "intro"); return PersonQuery(world, "texts") }
    var buttons: PersonQuery { precondition(kind == "intro"); return PersonQuery(world, "buttons") }
    var value: Any? { precondition(kind == "field"); return world.value }
    var isEnabled: Bool { kind == "field" ? world.fieldEnabled : world.buttonEnabled }
    var isHittable: Bool {
        switch kind {
        case "field": return world.introduction == 0
        case "explanation": return world.explanationHittable
        case "continue": return world.buttonHittable
        default: preconditionFailure("Unexpected hit test")
        }
    }
    var frame: CGRect {
        precondition(kind == "intro" || kind == "continue")
        return kind == "intro" ? world.introFrame : world.buttonFrame
    }
    func tap() {
        // Model the observed XCTest default handler cancelling the expected
        // form before the Continue element can receive its event.
        precondition(kind == "continue"); world.elementTaps += 1
        world.alerts = 0; world.introduction = 0
    }
}
@MainActor final class PersonHarness {
    func check(_ value: Bool, app: XCUIApplication, _ message: String) throws { if !value { throw Rejected() } }
    func capture(_ app: XCUIApplication, _ name: String) {
        app.world.captures += 1
        if app.world.mode == "changed-after-capture" { app.world.value = "Foreign person" }
        if app.world.mode == "cancel-after-capture" { Task.cancelled = true }
        if app.world.mode == "changed-button-frame" { app.world.buttonFrame.origin.x += 1 }
        if app.world.mode == "changed-intro-frame" { app.world.introFrame.origin.y -= 1 }
        if app.world.mode == "changed-root-frame" { app.world.rootFrame.size.width += 1 }
    }
    func wait(_ message: String, app: XCUIApplication, condition: () -> Bool) async throws {
        app.world.waits += 1
        if !condition() { throw Rejected() }
    }
    // ACTUAL_RECOVERY_PERSON_HELPER
    func run(_ app: XCUIApplication, expectedName: String, acknowledged: inout Bool) async throws {
        try await acknowledgeRecoveryPersonKeyboardIntroduction(app, expectedName: expectedName, acknowledged: &acknowledged)
    }
}
@main struct PersonMain {
    @MainActor static func main() async throws {
        let mode = CommandLine.arguments[1], world = PersonWorld(CommandLine.arguments[1])
        let app = XCUIApplication(world), harness = PersonHarness()
        var acknowledged = false, outcome = "returned"
        do {
            if ["pretype", "placeholder", "late", "repeated"].contains(mode) {
                world.value = mode == "placeholder" ? "Name or nickname" : ""
                try await harness.run(app, expectedName: world.value, acknowledged: &acknowledged)
                world.value = "Recovery Sentinel"
                if mode == "late" || mode == "repeated" { world.introduction = 1 }
                try await harness.run(app, expectedName: "Recovery Sentinel", acknowledged: &acknowledged)
            } else {
                try await harness.run(app, expectedName: "Recovery Sentinel", acknowledged: &acknowledged)
            }
        } catch is Cancelled { outcome = "cancelled" }
        catch { outcome = "rejected" }
        var result: [String: Any] = ["outcome": outcome, "acknowledged": acknowledged,
            "taps": world.taps, "captures": world.captures, "waits": world.waits]
        if mode == "app-origin" {
            result["appAnchor"] = world.appAnchor; result["elementTaps"] = world.elementTaps
            result["point"] = [world.point.x, world.point.y]
        }
        print(String(data: try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]), encoding: .utf8)!)
    }
}
'''


class RecoveryPersonIntroductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix='recovery-person-introduction-')
        cls.addClassCleanup(cls.scratch.cleanup)
        source = SOURCE.read_text()
        start = source.index('    private func acknowledgeRecoveryPersonKeyboardIntroduction(')
        end = source.index('    private func localStoreSession(', start)
        swift = Path(cls.scratch.name) / 'Person.swift'
        swift.write_text(RECOVERY_PERSON_INTRODUCTION.replace('    // ACTUAL_RECOVERY_PERSON_HELPER', source[start:end]))
        cls.binary = Path(cls.scratch.name) / 'person-tests'
        result = subprocess.run(['/usr/bin/swiftc', '-swift-version', '6', '-strict-concurrency=complete',
                                 '-parse-as-library', str(swift), '-o', str(cls.binary)],
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stderr)

    def probe(self, mode):
        result = subprocess.run([str(self.binary), mode], capture_output=True, text=True, check=True, timeout=5)
        return json.loads(result.stdout)

    def test_absent_introduction_has_no_action_or_wait(self):
        self.assertEqual(self.probe('absent'), {'outcome': 'returned', 'acknowledged': False,
                                              'taps': 0, 'captures': 0, 'waits': 0})

    def test_first_use_at_focus_or_during_typing_uses_one_acknowledgement(self):
        for mode in ['pretype', 'placeholder', 'late']:
            with self.subTest(mode=mode):
                self.assertEqual(self.probe(mode), {'outcome': 'returned', 'acknowledged': True,
                                                   'taps': 1, 'captures': 1, 'waits': 1})

    def test_only_unique_expected_intro_form_and_value_can_be_acknowledged(self):
        for mode in ['duplicate-intro', 'extra-alert', 'wrong-alert', 'extra-field', 'wrong-field',
                     'wrong-value', 'partial-value', 'disabled-field', 'missing-explanation',
                     'duplicate-explanation', 'hidden-explanation', 'missing-continue',
                     'duplicate-continue', 'disabled-continue', 'hidden-continue', 'background']:
            with self.subTest(mode=mode):
                result = self.probe(mode)
                self.assertEqual((result['outcome'], result['acknowledged'], result['taps']),
                                 ('rejected', False, 0))

    def test_changed_form_and_cancellation_do_not_tap(self):
        for mode, outcome in [('changed-after-capture', 'rejected'), ('cancelled', 'cancelled'),
                              ('cancel-after-capture', 'cancelled')]:
            with self.subTest(mode=mode):
                result = self.probe(mode)
                self.assertEqual((result['outcome'], result['acknowledged'], result['taps']),
                                 (outcome, False, 0))

    def test_reappearance_or_failed_dismissal_never_repeats_continue(self):
        for mode in ['repeated', 'stays-open', 'changed-after-tap']:
            with self.subTest(mode=mode):
                result = self.probe(mode)
                self.assertEqual((result['outcome'], result['acknowledged'], result['taps']),
                                 ('rejected', True, 1))

    def test_coordinate_uses_application_origin_and_avoids_element_interruption(self):
        self.assertEqual(self.probe('app-origin'), {
            'outcome': 'returned', 'acknowledged': True, 'taps': 1, 'captures': 1, 'waits': 1,
            'appAnchor': True, 'elementTaps': 0, 'point': [201, 829.5]})

    def test_invalid_or_changed_geometry_never_authorizes_continue(self):
        for mode in ['empty-button', 'nan-button', 'infinite-intro', 'button-outside-intro',
                     'intro-outside-app', 'empty-root', 'invalid-root',
                     'changed-button-frame', 'changed-intro-frame', 'changed-root-frame']:
            with self.subTest(mode=mode):
                result = self.probe(mode)
                self.assertEqual((result['outcome'], result['acknowledged'], result['taps']),
                                 ('rejected', False, 0))

    def test_disappeared_expected_form_is_not_accepted_as_acknowledgement(self):
        result = self.probe('form-dismissed')
        self.assertEqual((result['outcome'], result['acknowledged'], result['taps']),
                         ('rejected', True, 1))

    def test_recovery_retains_single_type_and_add_with_pre_post_intro_checks(self):
        source = SOURCE.read_text()
        start = source.index('    func testRecoveryExportFullBackupThroughFiles(')
        end = source.index('    func testRecoveryRestoreIntoEmptyFreeLibraryAndOpenOriginal(', start)
        case = source[start:end]
        self.assertEqual(case.count('var keyboardIntroductionAcknowledged = false'), 1)
        self.assertEqual(case.count('acknowledgeRecoveryPersonKeyboardIntroduction('), 2)
        self.assertEqual(case.count('name.typeText("Recovery Sentinel")'), 1)
        self.assertEqual(case.count('confirm.tap()'), 1)
        first = case.index('acknowledgeRecoveryPersonKeyboardIntroduction(')
        second = case.index('acknowledgeRecoveryPersonKeyboardIntroduction(', first + 1)
        self.assertLess(first, case.index('name.typeText("Recovery Sentinel")'))
        self.assertLess(case.index('name.typeText("Recovery Sentinel")'), second)
        self.assertLess(second, case.index('confirm.tap()'))
        self.assertIn('name.value as? String == "Recovery Sentinel"', case[second:case.index('confirm.tap()')])
        self.assertIn('UIContinuousPathIntroductionView").count == 0', case[second:case.index('confirm.tap()')])
        self.assertIn('app.staticTexts["Recovery Sentinel"].exists && app.staticTexts["Alex Example"].exists', case)
        self.assertIn('recoveryCounts(trips: 1, people: 2, documents: 1, app: app)', case)
        self.assertNotIn('timeout:', case[:case.index('save.tap()')])

if __name__ == '__main__':
    unittest.main(verbosity=2)
