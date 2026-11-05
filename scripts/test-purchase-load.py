#!/usr/bin/env python3
"""Run the actual load() control flow with deterministic async boundaries.

Only entitlement/catalog I/O is substituted. No StoreKit, app, or Simulator is
started. Checked continuations order overlapping calls without sleeps or races.
Readiness tests substitute only the UI values and clock in the actual UI-test
call and wait helpers. Native integration remains a separate CI requirement.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "App/PurchaseManager.swift"

FIXTURE = r'''
import Foundation

@MainActor
func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else {
        print("FAIL \(message)")
        exit(1)
    }
}

@MainActor
final class Gate {
    private(set) var entries = 0
    var maximumEntries = 2
    private var suspended: [Int: CheckedContinuation<Void, Never>] = [:]
    private var observers: [Int: CheckedContinuation<Void, Never>] = [:]

    func pause() async {
        entries += 1
        let entry = entries
        expect(entry <= maximumEntries, "Unexpected catalog reacquisition")
        await withCheckedContinuation { continuation in
            suspended[entry] = continuation
            observers.removeValue(forKey: entry)?.resume()
        }
    }

    func entered(_ entry: Int) async {
        if entries >= entry { return }
        await withCheckedContinuation { continuation in
            expect(observers[entry] == nil, "Duplicate gate observer")
            observers[entry] = continuation
        }
    }

    func release(_ entry: Int) {
        guard let continuation = suspended.removeValue(forKey: entry) else {
            preconditionFailure("Gate was not suspended")
        }
        continuation.resume()
    }
}

enum L10n {
    static func service(_ key: String, defaultValue: String) -> String { defaultValue }
}
enum CatalogFailure: Error { case unavailable }

@MainActor
final class Harness {
    var isBusy = false
    var isPro = false
    var displayPrice: String?
    var statusMessage: String?
    var failCatalog = false
    private(set) var refreshed = 0
    let entitlements = Gate()
    let catalog = Gate()

    init() { catalog.maximumEntries = 1 }

    func refreshEntitlements() async {
        await entitlements.pause()
        refreshed += 1
    }

    func loadProduct() async throws {
        await catalog.pause()
        if failCatalog { throw CatalogFailure.unavailable }
        displayPrice = "Fixture price"
    }

    // ACTUAL_LOAD
}

@main
struct Main {
    @MainActor
    static func main() async {
        let name = CommandLine.arguments[1]
        let manager = Harness()
        switch name {
        case "owner-reserves-before-entitlements":
            let owner = Task { await manager.load() }
            await manager.entitlements.entered(1)
            expect(manager.isBusy, "Load must reserve busy before its first await")
            manager.entitlements.release(1)
            await manager.catalog.entered(1)
            expect(manager.isBusy, "Catalog must retain the load reservation")
            manager.catalog.release(1)
            await owner.value
            expect(!manager.isBusy && manager.refreshed == 1, "Completed owner did not release busy")
            expect(manager.displayPrice == "Fixture price", "Catalog result was not retained")

        case "pending-load-completes-before-owner":
            let owner = Task { await manager.load() }
            await manager.entitlements.entered(1)
            manager.entitlements.release(1)
            await manager.catalog.entered(1)
            let pending = Task { await manager.load() }
            await manager.entitlements.entered(2)
            manager.entitlements.release(2)
            await pending.value
            expect(manager.isBusy, "Pending load released the catalog owner's reservation")
            expect(manager.catalog.entries == 1 && manager.refreshed == 2, "Busy refresh altered catalog ownership")
            manager.catalog.release(1)
            await owner.value
            expect(!manager.isBusy, "Catalog owner did not release its reservation")

        case "pending-load-never-reacquires", "pending-load-preserves-new-owner":
            let owner = Task { await manager.load() }
            await manager.entitlements.entered(1)
            manager.entitlements.release(1)
            await manager.catalog.entered(1)
            let pending = Task { await manager.load() }
            await manager.entitlements.entered(2)
            manager.catalog.release(1)
            await owner.value
            expect(!manager.isBusy, "First owner did not finish")
            let newOwner = name == "pending-load-preserves-new-owner"
            manager.isBusy = newOwner // A purchase/restore now owns the reservation.
            manager.entitlements.release(2)
            await pending.value
            expect(manager.catalog.entries == 1, "Pending load started a second catalog request")
            expect(manager.isBusy == newOwner, "Pending load changed another operation's reservation")
            expect(manager.refreshed == 2, "Busy load must still refresh entitlements")

        case "busy-load-preserves-owner", "busy-load-outlives-owner":
            manager.isBusy = true // Existing purchase/restore owns the reservation.
            manager.catalog.maximumEntries = 0
            let pending = Task { await manager.load() }
            await manager.entitlements.entered(1)
            let ownerStillBusy = name == "busy-load-preserves-owner"
            manager.isBusy = ownerStillBusy
            manager.entitlements.release(1)
            await pending.value
            expect(manager.catalog.entries == 0, "Busy-at-entry load must never acquire the catalog")
            expect(manager.isBusy == ownerStillBusy, "Busy load released a reservation it did not own")
            expect(manager.refreshed == 1, "Busy load skipped the entitlement refresh")

        case "catalog-error-releases-owner":
            manager.isPro = true
            manager.displayPrice = "Previous price"
            manager.failCatalog = true
            let owner = Task { await manager.load() }
            await manager.entitlements.entered(1)
            manager.entitlements.release(1)
            await manager.catalog.entered(1)
            manager.catalog.release(1)
            await owner.value
            expect(!manager.isBusy, "Catalog failure left the owner busy")
            expect(manager.isPro && manager.displayPrice == "Previous price", "Catalog failure erased existing state")
            expect(manager.statusMessage == "The App Store price is unavailable. Try again when connected. Your existing documents remain available.",
                   "Catalog failure lost its existing user message")

        default:
            preconditionFailure("Unknown regression case")
        }
        print("PASS \(name)")
    }
}
'''


def load_method(source):
    start = "    func load() async {"
    end = "\n    @discardableResult\n    func purchase("
    if source.count(start) != 1 or source.count(end) != 1:
        raise ValueError("Cannot identify the unique production load() boundary")
    return source[source.index(start):source.index(end, source.index(start))]


class PurchaseLoadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="tripdocket-purchase-load-")
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        swift = root / "main.swift"
        swift.write_text(FIXTURE.replace("    // ACTUAL_LOAD", load_method(SOURCE.read_text())))
        cls.executable = root / "purchase-load-tests"
        # Simulator-only diagnostics compile out, just as in the macOS target.
        # MainActor annotations remain real Swift concurrency checks.
        result = subprocess.run(["swiftc", "-swift-version", "6", "-parse-as-library",
                                 str(swift), "-o", str(cls.executable)],
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def run_case(self, name):
        result = subprocess.run([str(self.executable), name], capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "PASS " + name)

    def test_owner_reserves_before_entitlements(self):
        self.run_case("owner-reserves-before-entitlements")

    def test_pending_load_never_reacquires(self):
        self.run_case("pending-load-never-reacquires")

    def test_pending_load_completes_before_owner(self):
        self.run_case("pending-load-completes-before-owner")

    def test_pending_load_preserves_new_owner(self):
        self.run_case("pending-load-preserves-new-owner")

    def test_busy_load_preserves_owner(self):
        self.run_case("busy-load-preserves-owner")

    def test_busy_load_outlives_owner(self):
        self.run_case("busy-load-outlives-owner")

    def test_catalog_error_releases_owner(self):
        self.run_case("catalog-error-releases-owner")


READINESS_FIXTURE = r'''
import Foundation

@MainActor func expect(_ value: @autoclosure () -> Bool, _ message: String) {
    guard value() else { print("FAIL \(message)"); exit(1) }
}
@MainActor enum FixtureTime { static var elapsed = Duration.zero }
struct FixtureInstant: Comparable {
    let elapsed: Duration
    func advanced(by duration: Duration) -> Self { Self(elapsed: elapsed + duration) }
    static func < (lhs: Self, rhs: Self) -> Bool { lhs.elapsed < rhs.elapsed }
}
@MainActor struct FixtureClock {
    var now: FixtureInstant { FixtureInstant(elapsed: FixtureTime.elapsed) }
}
@MainActor enum FixtureSleep {
    static func sleep(for duration: Duration) async throws { FixtureTime.elapsed += duration }
}
@MainActor final class XCUIApplication { var alerts: [Int] = [] }
@MainActor final class FixtureBuy {
    var exists = true
    var enabled = true
    var isHittable = true
    var readyAt = Duration.seconds(35)
    var isEnabled: Bool { enabled && FixtureTime.elapsed >= readyAt }
}
struct PurchaseTestError: Error { let message: String }

@MainActor final class Harness {
    let app = XCUIApplication()
    let springboard = XCUIApplication()
    let buy = FixtureBuy()
    var diagnosticNames: [String] = []
    func attachDiagnostics(app: XCUIApplication, springboard: XCUIApplication, name: String) {
        diagnosticNames.append(name)
    }
    func check(attempt: Int) async throws {
        // ACTUAL_CALL
    }
    func checkDefault() async throws {
        try await require("default", app: app, springboard: springboard) { buy.isEnabled }
    }
    // ACTUAL_HELPERS
}

@main struct Main {
    @MainActor static func main() async {
        let name = CommandLine.arguments[1]
        let h = Harness()
        var attempt = 1
        var accepted = true
        var expectedTime = Duration.seconds(35)
        switch name {
        case "first-ready-35": break
        case "first-ready-59": h.buy.readyAt = .seconds(59); expectedTime = .seconds(59)
        case "first-too-late": h.buy.readyAt = .seconds(61); accepted = false; expectedTime = .seconds(60)
        case "second-stays-15": attempt = 2; accepted = false; expectedTime = .seconds(15)
        case "default-stays-15": accepted = false; expectedTime = .seconds(15)
        case "missing", "disabled", "not-hittable", "alert":
            h.buy.readyAt = .zero; accepted = false; expectedTime = .seconds(60)
            if name == "missing" { h.buy.exists = false }
            if name == "disabled" { h.buy.enabled = false }
            if name == "not-hittable" { h.buy.isHittable = false }
            if name == "alert" { h.app.alerts = [1] }
        case "already-ready": h.buy.readyAt = .zero; expectedTime = .zero
        default: fatalError("Unknown fixture")
        }
        var completed = false
        var failure: String?
        do {
            if name == "default-stays-15" { try await h.checkDefault() }
            else { try await h.check(attempt: attempt) }
            completed = true
        } catch let error as PurchaseTestError { failure = error.message }
        catch { fatalError("Unexpected error: \(error)") }
        expect(completed == accepted, "readiness result")
        expect(FixtureTime.elapsed == expectedTime, "original wait deadline")
        let message = name == "default-stays-15" ? "default" : "Purchase is not ready for failure attempt \(attempt)"
        expect(h.diagnosticNames == (accepted ? [] : [message]), "diagnostic path")
        expect(failure == (accepted ? nil : message), "failure preserved")
        print("PASS \(name)")
    }
}
'''


def readiness_fixture(source):
    def unique_section(start, end):
        if source.count(start) != 1 or source.count(end) != 1:
            raise ValueError("Cannot identify unique readiness boundary")
        return source[source.index(start):source.index(end, source.index(start))]

    call = unique_section('                try await require("Purchase is not ready for failure attempt',
                          '                try await session.setSimulatedError(.generic')
    helpers = unique_section('    private func require(\n', '    private func attachDiagnostics(')
    # Substitute the two clock/I/O operations, retaining the real deadline,
    # polling, final predicate, error and diagnostic control flow.
    if helpers.count('ContinuousClock()') != 1 or helpers.count('Task.sleep(') != 1:
        raise ValueError("Unexpected readiness clock operations")
    helpers = helpers.replace('ContinuousClock()', 'FixtureClock()').replace('Task.sleep(', 'FixtureSleep.sleep(')
    return READINESS_FIXTURE.replace('// ACTUAL_CALL', call).replace('// ACTUAL_HELPERS', helpers)


class PurchaseReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="tripdocket-purchase-readiness-")
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        source = (ROOT / "UITests/PurchaseUITests.swift").read_text()
        selected = 'timeout: attempt == 1 ? .seconds(60) : .seconds(15)'
        if source.count(selected) != 1:
            raise AssertionError("Expected one scoped initial-readiness policy")
        cls.executables = {}
        for name, text in (("actual", source), ("old-cap", source.replace(selected, selected.replace('60', '15')))):
            swift = root / (name + ".swift")
            swift.write_text(readiness_fixture(text))
            executable = root / name
            result = subprocess.run(["swiftc", "-swift-version", "6", "-parse-as-library",
                                     str(swift), "-o", str(executable)],
                                    capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            cls.executables[name] = executable

    def run_case(self, name, variant="actual"):
        result = subprocess.run([str(self.executables[variant]), name], capture_output=True,
                                text=True, timeout=5)
        if variant == "old-cap":
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), "FAIL readiness result")
        else:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), "PASS " + name)

    def test_initial_readiness_uses_bounded_extra_time(self):
        for case in ("first-ready-35", "first-ready-59", "already-ready"):
            with self.subTest(case=case):
                self.run_case(case)

    def test_old_initial_cap_causally_rejects_delayed_readiness(self):
        self.run_case("first-ready-35", "old-cap")

    def test_initial_readiness_still_expires(self):
        self.run_case("first-too-late")

    def test_subsequent_and_default_waits_remain_short(self):
        for case in ("second-stays-15", "default-stays-15"):
            with self.subTest(case=case):
                self.run_case(case)

    def test_all_readiness_predicates_remain_required(self):
        for case in ("missing", "disabled", "not-hittable", "alert"):
            with self.subTest(case=case):
                self.run_case(case)



CORE_TIMING_FIXTURE = r'''
import Foundation

struct PurchaseTestError: Error { let message: String }
enum FixtureFailure: Error { case deadline }
@MainActor enum UIDevice {
    enum Idiom { case phone, pad }
    struct Device {
        var userInterfaceIdiom: Idiom {
            ProcessInfo.processInfo.environment["FIXTURE_IDIOM"] == "pad" ? .pad : .phone
        }
    }
    static var current: Device { Device() }
}
@MainActor final class Harness {
    var executionTimeAllowance: TimeInterval = 777
    var sideEffects = 0
    let finishAfter: TimeInterval
    init(_ finishAfter: TimeInterval) { self.finishAfter = finishAfter }
    // ACTUAL_CASES
    // ACTUAL_SELECTOR
    private func verifyPurchaseFailureAlert(russian: Bool, diagnostics: Bool) async throws {
        // ACTUAL_PREFIX
        sideEffects += 1
        _ = (russian, diagnostics)
        // Only the native deadline is substituted: exercise the selected value
        // at a deterministic completion boundary, without starting XCTest/UI.
        if finishAfter >= executionTimeAllowance { throw FixtureFailure.deadline }
    }
}
@main struct Main {
    @MainActor static func main() async {
        let h = Harness(Double(CommandLine.arguments[2])!)
        var result = "passed"
        do {
            switch CommandLine.arguments[1] {
            case "en": try await h.testPurchaseFailureAlertInEnglishWithDiagnostics()
            case "ru": try await h.testPurchaseFailureAlertInRussianWithDiagnostics()
            case "no-diagnostics": try await h.testPurchaseFailureAlertWithoutDiagnosticFlag()
            default: fatalError("Unknown fixture case")
            }
        } catch is PurchaseTestError { result = "rejected" }
        catch FixtureFailure.deadline { result = "timedOut" }
        catch { fatalError("Unexpected fixture error") }
        print("\(result) \(h.executionTimeAllowance) \(h.sideEffects)")
    }
}
'''


def core_timing_fixture(source):
    """Use the real three callers, selector and pre-side-effect assignment."""
    cases_start = source.index('    func testPurchaseFailureAlertInEnglishWithDiagnostics()')
    selector_start = source.index('    private func failureAlertExecutionTimeAllowance()')
    helper_start = source.index('    private func verifyPurchaseFailureAlert(')
    prefix_start = source.index('\n', helper_start) + 1
    prefix_end = source.index('        continueAfterFailure = false', prefix_start)
    selector = source[selector_start:helper_start]
    boundary = '#if DEBUG && targetEnvironment(simulator) && arch(x86_64)'
    if selector.count(boundary) != 1:
        raise ValueError("Expected one native build boundary")
    # Compile both sides of the actual native selector on the offline host.
    selector = selector.replace(boundary, '#if CORE_SUPPORTED_FIXTURE')
    return (CORE_TIMING_FIXTURE.replace('// ACTUAL_CASES', source[cases_start:selector_start])
            .replace('// ACTUAL_SELECTOR', selector)
            .replace('// ACTUAL_PREFIX', source[prefix_start:prefix_end]))


class PurchaseCoreTimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="tripdocket-core-timing-")
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        source = (ROOT / 'UITests/PurchaseUITests.swift').read_text()
        fixture = core_timing_fixture(source)
        if fixture.count('try useHostedCoreTiming() ? 360 : 240') != 1:
            raise AssertionError("Expected one selected hosted allowance")
        cls.binaries = {}
        for name, text, flags in (
            ('supported', fixture, ['-D', 'CORE_SUPPORTED_FIXTURE']),
            ('unsupported', fixture, []),
            ('old-allowance', fixture.replace('try useHostedCoreTiming() ? 360 : 240', 'try useHostedCoreTiming() ? 240 : 240'), ['-D', 'CORE_SUPPORTED_FIXTURE']),
        ):
            swift = root / (name + '.swift')
            swift.write_text(text)
            executable = root / name
            result = subprocess.run(['swiftc', '-swift-version', '6', '-parse-as-library',
                                     *flags, str(swift), '-o', str(executable)],
                                    capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            cls.binaries[name] = executable

    def invoke(self, token=None, *, case='en', finish=0, variant='supported', extra=None):
        environment = os.environ.copy()
        for key in ('TRIPDOCKET_CORE_TIMING', 'TRIPDOCKET_PHONE_TIMING',
                    'TRIPDOCKET_IPAD_TIMING', 'FIXTURE_IDIOM'):
            environment.pop(key, None)
        if token is not None:
            environment['TRIPDOCKET_CORE_TIMING'] = token
        environment.update(extra or {})
        result = subprocess.run([str(self.binaries[variant]), case, str(finish)],
                                env=environment, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.strip()

    def test_three_actual_callers_select_only_hosted_allowance(self):
        for case in ('en', 'ru', 'no-diagnostics'):
            with self.subTest(case=case):
                self.assertEqual(self.invoke('hosted-intel-core-v1', case=case, finish=314.213),
                                 'passed 360.0 1')
                self.assertEqual(self.invoke(case=case, finish=239), 'passed 240.0 1')

    def test_selected_allowance_remains_a_hard_boundary(self):
        for finish in (360, 361):
            with self.subTest(finish=finish):
                self.assertEqual(self.invoke('hosted-intel-core-v1', finish=finish), 'timedOut 360.0 1')
        self.assertEqual(self.invoke(finish=240), 'timedOut 240.0 1')

    def test_old_hosted_allowance_causally_rejects_same_completion(self):
        self.assertEqual(self.invoke('hosted-intel-core-v1', finish=314.213,
                                     variant='old-allowance'), 'timedOut 240.0 1')

    def test_invalid_or_conflicting_tokens_fail_before_side_effects(self):
        for case in ('en', 'ru', 'no-diagnostics'):
            for token, extra in (
                ('', {}), ('hosted-intel-core-v2', {}),
                ('hosted-intel-core-v1', {'TRIPDOCKET_PHONE_TIMING': ''}),
                ('hosted-intel-core-v1', {'TRIPDOCKET_IPAD_TIMING': 'hosted-intel-ipad-en-v1'}),
                ('hosted-intel-core-v1', {'FIXTURE_IDIOM': 'pad'}),
            ):
                with self.subTest(case=case, token=token, extra=extra):
                    self.assertEqual(self.invoke(token, case=case, extra=extra), 'rejected 777.0 0')

    def test_unsupported_build_rejects_token_but_keeps_default(self):
        self.assertEqual(self.invoke('hosted-intel-core-v1', variant='unsupported'), 'rejected 777.0 0')
        self.assertEqual(self.invoke(variant='unsupported'), 'passed 240.0 1')
        self.assertEqual(self.invoke(extra={'TRIPDOCKET_PHONE_TIMING': 'hosted-intel-phone-v1'}),
                         'passed 240.0 1')



SYSTEM_SHEET_FIXTURE = r'''
import Foundation
struct PurchaseTestError: Error { let message: String }
@MainActor enum UIDevice {
    enum Idiom { case phone, pad }
    struct Device {
        var userInterfaceIdiom: Idiom {
            ProcessInfo.processInfo.environment["FIXTURE_IDIOM"] == "pad" ? .pad : .phone
        }
    }
    static var current: Device { Device() }
}
@MainActor enum SheetState {
    static var elapsed = Duration.zero
    static var appAt: Duration? = nil
    static var springboardAt: Duration? = nil
    static var appCost = Duration.zero
    static var springboardCost = Duration.zero
    static var reads: [String] = []
    static var checks = 0
    static var cancelAtCheck = -1
    static var cancelOnSleep = false
    static var cancelled = false
}
struct SheetInstant: Comparable {
    let elapsed: Duration
    func advanced(by value: Duration) -> SheetInstant { SheetInstant(elapsed: elapsed + value) }
    static func < (lhs: SheetInstant, rhs: SheetInstant) -> Bool { lhs.elapsed < rhs.elapsed }
}
@MainActor struct SheetClock { var now: SheetInstant { SheetInstant(elapsed: SheetState.elapsed) } }
@MainActor enum SheetTask {
    static func checkCancellation() throws {
        SheetState.checks += 1
        if SheetState.cancelled || SheetState.checks == SheetState.cancelAtCheck { throw CancellationError() }
    }
    static func sleep(for duration: Duration) async throws {
        if SheetState.cancelOnSleep { throw CancellationError() }
        SheetState.elapsed += duration
    }
}
@MainActor final class XCUIApplication {
    let owner: String
    init(_ owner: String) { self.owner = owner }
}
@MainActor struct SheetMarker {
    let owner: String
    var exists: Bool {
        precondition(SheetState.reads.count < 3000)
        SheetState.reads.append(owner)
        SheetState.elapsed += owner == "app" ? SheetState.appCost : SheetState.springboardCost
        guard let at = owner == "app" ? SheetState.appAt : SheetState.springboardAt else { return false }
        return SheetState.elapsed >= at
    }
}
@MainActor final class Harness {
    var executionTimeAllowance: TimeInterval = 777
    var sideEffects = 0
    var diagnosticNames: [String] = []
    var observations = 0
    let app = XCUIApplication("app")
    let springboard = XCUIApplication("springboard")
    enum Point { case missingSheet }
    func recordCancellationSessionSettings(_ session: Int, point: Point) { observations += 1 }
    func recordFullPurchaseState(_ app: XCUIApplication) { observations += 1 }
    func attachDiagnostics(app: XCUIApplication, springboard: XCUIApplication, name: String) {
        diagnosticNames.append(name)
    }
    func xcodeMarker(in app: XCUIApplication) -> SheetMarker { SheetMarker(owner: app.owner) }
    // ACTUAL_SELECTOR
    // ACTUAL_OBSERVER
    func run() async throws {
        // ACTUAL_PREFIX
        sideEffects += 1
        let session = 0
        // ACTUAL_OBSERVATION_CALL
    }
}
@main struct Main {
    @MainActor static func main() async {
        let name = CommandLine.arguments[1]
        switch name {
        case "delayed": SheetState.springboardAt = .milliseconds(79300)
        case "app-ready": SheetState.appAt = .zero
        case "last-valid": SheetState.appAt = .zero; SheetState.appCost = .milliseconds(119900)
        case "app-boundary": SheetState.appAt = .zero; SheetState.appCost = .seconds(120)
        case "app-late": SheetState.appAt = .zero; SheetState.appCost = .seconds(121)
        case "springboard-late": SheetState.springboardAt = .zero; SheetState.springboardCost = .seconds(121)
        case "slow-false": SheetState.appCost = .seconds(121)
        case "never": break
        case "cancel-before-app": SheetState.cancelAtCheck = 1
        case "cancel-after-app": SheetState.cancelAtCheck = 2; SheetState.appAt = .zero
        case "cancel-before-springboard": SheetState.cancelAtCheck = 3
        case "cancel-after-springboard": SheetState.cancelAtCheck = 4; SheetState.springboardAt = .zero
        case "cancel-sleep": SheetState.cancelOnSleep = true
        default: fatalError("Unknown scenario")
        }
        let h = Harness()
        var result = "passed"
        do { try await h.run() }
        catch is CancellationError { result = "cancelled" }
        catch let error as PurchaseTestError { result = error.message }
        catch { fatalError("Unexpected error: \(error)") }
        let c = SheetState.elapsed.components
        let row: [String: Any] = ["result": result, "allowance": h.executionTimeAllowance,
            "sideEffects": h.sideEffects, "diagnostics": h.diagnosticNames,
            "observations": h.observations, "appReads": SheetState.reads.filter { $0 == "app" }.count,
            "springboardReads": SheetState.reads.filter { $0 == "springboard" }.count,
            "elapsed": Double(c.seconds) + Double(c.attoseconds) / 1e18]
        print(String(data: try! JSONSerialization.data(withJSONObject: row, options: [.sortedKeys]), encoding: .utf8)!)
    }
}
'''


def system_sheet_fixture(source):
    case_start = source.index('    func testCancellingSystemPurchaseSheetKeepsFreeAccess()')
    prefix_start = source.index('\n', case_start) + 1
    prefix_end = source.index('        continueAfterFailure = false', prefix_start)
    call_start = source.index('        do {', prefix_end)
    call_end = source.index('        let paymentSurface =', call_start)
    selector_start = source.index('    private func failureAlertExecutionTimeAllowance()')
    selector_end = source.index('    private func verifyPurchaseFailureAlert(', selector_start)
    observer_start = source.index('    private func waitForSystemPurchaseSheet(')
    observer_end = source.index('    private func require(\n', observer_start)
    observer = source[observer_start:observer_end]
    if observer.count('ContinuousClock()') != 1 or observer.count('Task.checkCancellation()') != 4:
        raise ValueError("Expected fixed clock and pre/post checks for both queries")
    observer = observer.replace('ContinuousClock()', 'SheetClock()').replace('Task.', 'SheetTask.')
    selector = source[selector_start:selector_end].replace(
        '#if DEBUG && targetEnvironment(simulator) && arch(x86_64)', '#if CORE_SUPPORTED_FIXTURE')
    return (SYSTEM_SHEET_FIXTURE.replace('// ACTUAL_PREFIX', source[prefix_start:prefix_end])
            .replace('// ACTUAL_OBSERVATION_CALL', source[call_start:call_end])
            .replace('// ACTUAL_SELECTOR', selector).replace('// ACTUAL_OBSERVER', observer))


class SystemSheetObservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='tripdocket-system-sheet-')
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        cls.source = (ROOT / 'UITests/PurchaseUITests.swift').read_text()
        actual = system_sheet_fixture(cls.source)
        cls.binaries = {}
        mutant = actual
        for query in ('let inApp = xcodeMarker(in: app).exists',
                      'let inSpringboard = xcodeMarker(in: springboard).exists'):
            before = query + '\n            try SheetTask.checkCancellation()\n            guard clock.now < deadline else { return false }'
            if mutant.count(before) != 1:
                raise AssertionError('Missing actual post-query boundary')
            mutant = mutant.replace(before, query + '\n            try SheetTask.checkCancellation()')
        for name, text, flags in [('supported', actual, ['-D', 'CORE_SUPPORTED_FIXTURE']),
                                  ('unsupported', actual, []),
                                  ('unchecked-late', mutant, ['-D', 'CORE_SUPPORTED_FIXTURE'])]:
            swift = root / (name + '.swift'); swift.write_text(text)
            binary = root / name
            result = subprocess.run(['swiftc', '-swift-version', '6', '-parse-as-library',
                                     *flags, str(swift), '-o', str(binary)],
                                    capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            cls.binaries[name] = binary

    def invoke(self, scenario, token='hosted-intel-core-v1', *, variant='supported', extra=None):
        import json
        env = os.environ.copy()
        for key in ('TRIPDOCKET_CORE_TIMING', 'TRIPDOCKET_PHONE_TIMING', 'TRIPDOCKET_IPAD_TIMING', 'FIXTURE_IDIOM'):
            env.pop(key, None)
        if token is not None: env['TRIPDOCKET_CORE_TIMING'] = token
        env.update(extra or {})
        run = subprocess.run([str(self.binaries[variant]), scenario], env=env,
                             capture_output=True, text=True, timeout=5)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return json.loads(run.stdout)

    def test_actual_call_accepts_delayed_sheet_only_with_hosted_window(self):
        hosted = self.invoke('delayed')
        self.assertEqual(hosted['result'], 'passed')
        self.assertEqual(hosted['allowance'], 360)
        self.assertEqual(hosted['elapsed'], 79.3)
        self.assertEqual(hosted['diagnostics'], [])
        ordinary = self.invoke('delayed', None)
        self.assertEqual(ordinary['result'], 'No Xcode payment sheet appeared')
        self.assertEqual(ordinary['elapsed'], 15)
        self.assertEqual(ordinary['allowance'], 777)  # The runner owns its default.
        self.assertEqual(ordinary['diagnostics'], ['No Xcode payment sheet appeared'])
        self.assertEqual(ordinary['observations'], 2)

    def test_exact_and_late_matches_are_not_accepted(self):
        for name in ('app-boundary', 'app-late', 'springboard-late', 'slow-false', 'never'):
            with self.subTest(name=name):
                row = self.invoke(name)
                self.assertEqual(row['result'], 'No Xcode payment sheet appeared')
        self.assertEqual(self.invoke('slow-false')['springboardReads'], 0)
        self.assertEqual(self.invoke('last-valid')['result'], 'passed')
        self.assertEqual(self.invoke('app-ready')['springboardReads'], 0)

    def test_removing_actual_post_query_guards_causally_accepts_late_sheet(self):
        for name in ('app-boundary', 'app-late', 'springboard-late'):
            with self.subTest(name=name):
                self.assertEqual(self.invoke(name, variant='unchecked-late')['result'], 'passed')
                self.assertEqual(self.invoke(name)['result'], 'No Xcode payment sheet appeared')

    def test_cancellation_propagates_at_every_query_boundary_and_sleep(self):
        for name, app, spring in [('cancel-before-app', 0, 0), ('cancel-after-app', 1, 0),
                                  ('cancel-before-springboard', 1, 0), ('cancel-after-springboard', 1, 1),
                                  ('cancel-sleep', 1, 1)]:
            with self.subTest(name=name):
                row = self.invoke(name)
                self.assertEqual(row['result'], 'cancelled')
                self.assertEqual((row['appReads'], row['springboardReads']), (app, spring))
                self.assertEqual(row['diagnostics'], [])
                self.assertEqual(row['observations'], 2)  # The actual catch rethrows CancellationError.

    def test_invalid_profiles_reject_before_side_effects_or_native_queries(self):
        for token, extra in [('', {}), ('hosted-intel-core-v2', {}),
                             ('hosted-intel-core-v1', {'TRIPDOCKET_PHONE_TIMING': ''}),
                             ('hosted-intel-core-v1', {'TRIPDOCKET_IPAD_TIMING': ''}),
                             ('hosted-intel-core-v1', {'FIXTURE_IDIOM': 'pad'})]:
            with self.subTest(token=token, extra=extra):
                row = self.invoke('app-ready', token, extra=extra)
                self.assertNotEqual(row['result'], 'passed')
                self.assertEqual((row['allowance'], row['sideEffects'], row['appReads']), (777, 0, 0))
        self.assertEqual(self.invoke('app-ready', variant='unsupported')['sideEffects'], 0)
        for variant in ('supported', 'unsupported'):
            row = self.invoke('app-ready', None, variant=variant)
            self.assertEqual((row['result'], row['allowance']), ('passed', 777))

    def test_original_purchase_and_cancel_actions_stay_single(self):
        case = self.source.split('    func testCancellingSystemPurchaseSheetKeepsFreeAccess()', 1)[1].split(
            '    func testPurchaseFailureAlertInEnglishWithDiagnostics()', 1)[0]
        self.assertEqual(case.count('buy.tap()'), 1)
        self.assertEqual(case.count('try XCTUnwrap(cancel).tap()'), 1)
        self.assertIn('self.xcodeMarker(in: app).exists && !self.xcodeMarker(in: springboard).exists',
                      case.replace('\n                ', ' '))
        self.assertIn('XCTAssertTrue(session.allTransactions().isEmpty', case)
        self.assertIn('Cancellation unexpectedly removed the free trip limit', case)

if __name__ == "__main__":
    unittest.main()
