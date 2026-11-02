#!/usr/bin/env python3
"""Run the actual load() control flow with deterministic async boundaries.

Only entitlement/catalog I/O is substituted. No StoreKit, app, or Simulator is
started. Checked continuations order overlapping calls without sleeps or races.
Native purchase/restore integration tests remain a separate CI requirement.
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


if __name__ == "__main__":
    unittest.main()
