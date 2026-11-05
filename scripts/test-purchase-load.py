#!/usr/bin/env python3
"""Run the actual load() control flow with deterministic async boundaries.

Only entitlement/catalog I/O is substituted. No StoreKit, app, or Simulator is
started. Checked continuations order overlapping calls without sleeps or races.
Readiness tests substitute only the UI values and clock in the actual UI-test
call and wait helpers. Native integration remains a separate CI requirement.
"""
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
