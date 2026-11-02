#!/usr/bin/env python3
"""Exercise actual combined-batch UI state/configuration/ACK code without XCTest.

Only notification I/O, the monotonic clock and sleep are substituted. No native
application, Simulator or real Darwin notification is started by these guards.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'UITests/BatchImportUITests.swift'

SWIFT = r'''
import Foundation
import Darwin
import notify

@MainActor enum Fake {
    static var mode = CommandLine.arguments[1]
    static var time = 0.0
    static var registrations = 0
    static var cancellations = 0
    static var reads = 0
    static var cancelled = false
    static var names: [String] = []
    static var markers: [String] = []
    static func register(_ name: String, _ token: inout Int32) -> UInt32 {
        registrations += 1; names.append(name); token = 7
        if mode == "setup-expired" { time = 61 }
        return mode == "register-failure" ? 1 : 0
    }
    static func cancel(_ token: Int32) -> UInt32 {
        precondition(token == 7); cancellations += 1; return 0
    }
    static func read(_ token: Int32, _ state: inout UInt64) -> UInt32 {
        precondition(token == 7); reads += 1; state = 0
        if mode == "initial-read-failure" || (mode == "read-failure" && reads > 1) { return 1 }
        if reads == 1 && mode == "initial-nonzero" { state = 1 }
        if reads > 1 {
            if mode == "cancelled-after-read" { cancelled = true; state = 1 }
            if mode == "wrong-ack" { state = 2 }
            if mode == "at-deadline" { time = 60; state = 1 }
            if ["valid", "duplicate-consumer", "producer-after-consumer"].contains(mode) { state = 1 }
            if ["delayed", "case-clipped"].contains(mode) && time >= 12 { state = 1 }
        }
        return 0
    }
    static func checkCancellation() throws {
        if mode == "cancelled-immediate" || cancelled { throw CancellationError() }
    }
    static func sleep(for duration: Duration) async throws {
        if mode == "cancelled" { throw CancellationError() }
        time = ((time + seconds(duration)) * 1e9).rounded() / 1e9
    }
    nonisolated static func seconds(_ duration: Duration) -> Double {
        Double(duration.components.seconds) + Double(duration.components.attoseconds) / 1e18
    }
}
@MainActor struct FakeClock {
    struct Instant: Comparable {
        let value: Double
        func advanced(by duration: Duration) -> Instant { Instant(value: value + Fake.seconds(duration)) }
        func duration(to other: Instant) -> Duration { .nanoseconds(Int64(((other.value - value) * 1e9).rounded())) }
        static func < (lhs: Instant, rhs: Instant) -> Bool { lhs.value < rhs.value }
    }
    var now: Instant { Instant(value: Fake.time) }
}
@MainActor func print(_ value: String) { Fake.markers.append(value) }

@MainActor final class Harness {
    private struct BatchTestFailure: Error { let message: String }
    // ACTUAL_HELPERS
    static let session = "1A5C10F8-85FD-473F-9CF3-6B12E9D82F61"
    static let token = "4a6d3b20-c0cf-4c93-a6c8-9ba97bd9b5f3"
    static var validEnvironment: [String: String] {
        ["TRIPDOCKET_COMBINED_BATCH_UI": "1",
         "TRIPDOCKET_BATCH_CHECKPOINT_SESSION": session,
         "TRIPDOCKET_NATIVE_ROOT_UI": "1", "TRIPDOCKET_NATIVE_ROOT_TOKEN": token,
         "TRIPDOCKET_NATIVE_SEED_UI": "1", "TRIPDOCKET_NATIVE_SEED_TOKEN": token,
         "TRIPDOCKET_BATCH_UI": "1", "TRIPDOCKET_BATCH_FOLDER": "TripDocket-Batch-QA-" + token]
    }
    static func configurationTests() throws {
        let absent = try combinedBatchConfiguration([:], debugSimulator: false)
        let standalone = try combinedBatchConfiguration(["TRIPDOCKET_BATCH_UI": "1"], debugSimulator: false)
        precondition(absent == nil && standalone == nil)
        let valid = try combinedBatchConfiguration(validEnvironment, debugSimulator: true)
        precondition(valid == BatchCheckpointIdentity(session: session, token: token))
        var rejected = 0
        func reject(_ env: [String: String], debug: Bool = true) {
            do { _ = try combinedBatchConfiguration(env, debugSimulator: debug) }
            catch { rejected += 1; return }
            preconditionFailure("Malformed combined mode was accepted")
        }
        reject(validEnvironment, debug: false)
        reject(["TRIPDOCKET_COMBINED_BATCH_UI": "1"])
        reject(["TRIPDOCKET_BATCH_CHECKPOINT_SESSION": session])
        for key in validEnvironment.keys {
            var env = validEnvironment; env[key] = "invalid"; reject(env)
        }
        for session in [session.lowercased(), "1A5C10F8-85FD-173F-9CF3-6B12E9D82F61", "1A5C10F8-85FD-473F-1CF3-6B12E9D82F61"] {
            var env = validEnvironment; env["TRIPDOCKET_BATCH_CHECKPOINT_SESSION"] = session; reject(env)
        }
        var env = validEnvironment; env["TRIPDOCKET_NATIVE_ROOT_TOKEN"] = token.uppercased(); reject(env)
        env = validEnvironment; env["TRIPDOCKET_NATIVE_SEED_TOKEN"] = "79c64b87-b267-475c-bbe7-5df834742dd6"; reject(env)
        precondition(rejected == 16)
    }
    func run() async throws {
        if Fake.mode == "configuration" { try Self.configurationTests(); return }
        let identity = try Self.combinedBatchConfiguration(Self.validEnvironment, debugSimulator: true)!
        var recorded = identity
        if Fake.mode == "wrong-session" { recorded = BatchCheckpointIdentity(session: "79C64B87-B267-475C-BBE7-5DF834742DD6", token: identity.token) }
        if Fake.mode == "wrong-token" { recorded = BatchCheckpointIdentity(session: identity.session, token: "79c64b87-b267-475c-bbe7-5df834742dd6") }
        if !["missing-producer", "runner-restart"].contains(Fake.mode) { try Self.recordBatchProducer(recorded) }
        if Fake.mode == "duplicate-producer" { try Self.recordBatchProducer(identity) }
        let deadline = FakeClock.Instant(value: Fake.mode == "expired" ? 0 : Fake.mode == "case-clipped" ? 3 : 600)
        try await awaitBatchCheckpoint(identity, until: deadline)
        if Fake.mode == "duplicate-consumer" { try await awaitBatchCheckpoint(identity, until: deadline) }
        if Fake.mode == "producer-after-consumer" { try Self.recordBatchProducer(identity) }
    }
}
@main struct Main {
    @MainActor static func main() async {
        var succeeded = false
        do { try await Harness().run(); succeeded = true } catch {}
        let allowed = ["valid", "delayed", "configuration"]
        precondition(succeeded == allowed.contains(Fake.mode))
        if Fake.mode == "configuration" { Swift.print("PASS configuration"); return }
        let beforeRegistration = ["missing-producer", "runner-restart", "wrong-session", "wrong-token", "duplicate-producer", "expired", "cancelled-immediate"]
        precondition(Fake.registrations == (beforeRegistration.contains(Fake.mode) ? 0 : 1))
        precondition(Fake.cancellations == (Fake.mode == "register-failure" ? 0 : Fake.registrations))
        let beforeMarker = beforeRegistration + ["register-failure", "initial-read-failure", "initial-nonzero", "setup-expired"]
        precondition(Fake.markers.count == (beforeMarker.contains(Fake.mode) ? 0 : 1))
        if let marker = Fake.markers.first {
            let fields = marker.split(separator: " ").map(String.init)
            precondition(fields.count == 4 && fields[0] == "TRIPDOCKET_BATCH_CHECKPOINT")
            precondition(fields[1] == Harness.session && fields[2] == Harness.token)
            let nonce = UUID(uuidString: fields[3])!
            precondition(nonce.uuidString == fields[3] && nonce.uuid.6 & 0xf0 == 0x40)
            precondition(Fake.names == ["com.4alvit.tripfolio.batch-checkpoint." + fields[1] + "." + fields[3]])
        }
        if ["timeout", "at-deadline"].contains(Fake.mode) { precondition(Fake.time >= 60 && Fake.time < 60.01) }
        if Fake.mode == "case-clipped" { precondition(Fake.time >= 3 && Fake.time < 3.01) }
        if Fake.mode == "delayed" { precondition(Fake.time >= 12 && Fake.time < 13) }
        Swift.print("PASS " + Fake.mode)
    }
}
'''


def actual_helpers(text):
    start = text.index('    // Combined qualification preserves separate seed/main XCTest cases.')
    end = text.index('    @MainActor\n    private func nativeFolderBlankPoint(', start)
    return text[start:end]


class CheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = SOURCE.read_text()
        helpers = actual_helpers(source)
        # Substitute external I/O and time boundaries only, not branch logic.
        for old, new in {'notify_register_check': 'Fake.register', 'notify_cancel': 'Fake.cancel',
                         'notify_get_state': 'Fake.read', 'ContinuousClock': 'FakeClock',
                         'Task.sleep': 'Fake.sleep', 'Task.checkCancellation': 'Fake.checkCancellation'}.items():
            helpers = helpers.replace(old, new)
        cls.directory = tempfile.TemporaryDirectory(prefix='tripdocket-batch-checkpoint-')
        cls.addClassCleanup(cls.directory.cleanup)
        path = Path(cls.directory.name) / 'main.swift'
        path.write_text(SWIFT.replace('    // ACTUAL_HELPERS', helpers))
        cls.binary = Path(cls.directory.name) / 'checkpoint'
        result = subprocess.run(['swiftc', '-swift-version', '6', '-parse-as-library', str(path), '-o', str(cls.binary)],
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def test_configuration_and_single_consumption(self):
        for case in ['configuration', 'valid', 'missing-producer', 'runner-restart', 'wrong-session',
                     'wrong-token', 'duplicate-producer', 'duplicate-consumer', 'producer-after-consumer']:
            with self.subTest(case=case):
                r = subprocess.run([str(self.binary), case], capture_output=True, text=True, timeout=5, check=True)
                self.assertEqual(r.stdout.strip(), 'PASS ' + case)

    def test_bounded_exact_ack_and_cleanup(self):
        for case in ['delayed', 'register-failure', 'initial-read-failure', 'initial-nonzero',
                     'read-failure', 'wrong-ack', 'timeout', 'at-deadline', 'case-clipped',
                     'expired', 'setup-expired', 'cancelled', 'cancelled-immediate', 'cancelled-after-read']:
            with self.subTest(case=case):
                r = subprocess.run([str(self.binary), case], capture_output=True, text=True, timeout=5, check=True)
                self.assertEqual(r.stdout.strip(), 'PASS ' + case)

    def test_checkpoint_precedes_existing_consumer_actions(self):
        source = SOURCE.read_text()
        main = source[source.index('    func testRealFilesBatchRequiresEveryReviewAndPreservesOriginals()'):source.index('    func testRecoveryPrepareFilesProvider()')]
        checkpoint = main.index('try await awaitBatchCheckpoint(')
        for action in ['app.terminate()', 'localStoreSession()', 'app.launch()']:
            self.assertLess(checkpoint, main.index(action))
        self.assertIn('executionTimeAllowance = 600', main)
        seed = source[source.index('    func testNativeSaveSeedsBothSyntheticOriginals()'):source.index('    // Combined qualification preserves')]
        self.assertIn('executionTimeAllowance = 180', seed)
        self.assertIn('defer { app.terminate() }', seed)
        ordinary, control = seed.rsplit('        if reopenControl {', 1)
        control, completion = control.split('        // Host compares both exact destination bytes;', 1)
        self.assertEqual((ordinary + completion).count('.tap()'), 2)  # source and direct-export Save
        self.assertEqual(control.count('.tap()'), 1)
        self.assertIn('reopen.tap()', control)
        self.assertIn('let reopenControl = reopenValue == "1"', ordinary)
        self.assertIn('guard !reopenControl || (nativeRoot && checkpoint != nil)', ordinary)
        self.assertIn('try check(verified.exists && !failed.exists', control)
        self.assertIn('throw error', control)
        self.assertNotIn('recordBatchProducer(', control)
        self.assertIn('try Self.recordBatchProducer(', completion)
        verified = seed.index('try check(!failed.exists && verified.allSatisfy { $0.exists }')
        self.assertLess(seed.index('save.tap()'), verified)
        self.assertLess(verified, seed.index('capture(app, "Native seed returned after Save'))
        self.assertGreater(seed.index('try Self.recordBatchProducer('), seed.index('capture(app, "Native seed returned after Save'))
        self.assertNotIn('awaitBatchCheckpoint(', seed)


if __name__ == '__main__':
    unittest.main(verbosity=2)
