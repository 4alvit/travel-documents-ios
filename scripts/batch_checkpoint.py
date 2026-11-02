"""Bounded one-shot checkpoint protocol for qualifier-owned combined batch runs."""
import hashlib
import math
import os
from pathlib import Path
import re
import stat
import time
import uuid

PREFIX = 'TRIPDOCKET_BATCH_CHECKPOINT'
CHANNEL = 'com.4alvit.tripfolio.batch-checkpoint'
TRANSPORT_SECONDS = 60
MAX_LOG = 16 * 1024 * 1024
MAX_LINE = 256 * 1024
PREPARATION_TESTS = (
    'TripfolioTests/PlatformTests/testVerifiedPurchaseAndRestoreFromLocalHistory',
    'TripfolioUITests/BatchImportUITests/testRecoveryPrepareFilesProvider',
)
PREPARATION_CASES = tuple(test.split('/', 1)[1] + '()' for test in PREPARATION_TESTS)
TESTS = (
    'TripfolioUITests/BatchImportUITests/testNativeSaveSeedsBothSyntheticOriginals',
    'TripfolioUITests/BatchImportUITests/testRealFilesBatchRequiresEveryReviewAndPreservesOriginals',
)
CASES = tuple(test.split('/', 1)[1] + '()' for test in TESTS)


def require(ok, message):
    if not ok: raise RuntimeError(message)


def upper_uuid(value):
    require(isinstance(value, str), 'Missing checkpoint UUID')
    parsed = uuid.UUID(value)
    require(parsed.version == 4 and str(parsed).upper() == value, 'Invalid checkpoint UUID')
    return value


class NativeCaseFailed(RuntimeError):
    pass


class Transcript:
    def __init__(self, session, token):
        self.session = upper_uuid(session)
        require(str(uuid.UUID(token)) == token, 'Invalid checkpoint run token')
        self.token = token
        self.events = []; self.request = None; self.lines = 0
        self.prefixes = []
        for test in TESTS:
            target, cls, method = test.split('/')
            self.prefixes.append(f"Test Case '-[{target}.{cls} {method}]' ")

    def line(self, raw):
        require(isinstance(raw, bytes) and len(raw) <= MAX_LINE and b'\0' not in raw,
                'Invalid or oversized checkpoint log line')
        text = raw.decode('utf-8', 'strict').removesuffix('\r')
        self.lines += 1
        for index, prefix in enumerate(self.prefixes):
            if not text.startswith(prefix): continue
            suffix = text[len(prefix):]
            match = re.fullmatch(r'passed \(((?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,9})?) seconds\)\.', suffix)
            if re.fullmatch(r'failed \([0-9]+(?:\.[0-9]+)? seconds\)\.', suffix):
                raise NativeCaseFailed('Selected native case failed')
            event = 'started' if suffix == 'started.' else 'passed' if match else None
            require(event is not None, 'Selected checkpoint case failed or has malformed event')
            expected_index, expected_event = divmod(len(self.events), 2)
            require(index == expected_index and event == ('started' if expected_event == 0 else 'passed'),
                    'Combined cases are duplicated or not in strict observed order')
            if index == 1 and event == 'passed': require(self.request is not None, 'Main passed without checkpoint')
            if match:
                require(float(match[1]) <= (180, 600)[index], 'Selected native case exceeded its allowance')
            self.events.append({'case': CASES[index], 'event': event, 'line': self.lines,
                                'duration_seconds': match[1] if match else None})
            return None
        require(not text.startswith("Test Case '-["), 'Unexpected test case in combined transcript')
        if PREFIX not in text: return None
        fields = text.split(' ')
        require(len(fields) == 4 and fields[0] == PREFIX
                and fields[1] == self.session and fields[2] == self.token,
                'Malformed, stale or foreign checkpoint marker')
        nonce = upper_uuid(fields[3])
        require(self.request is None and len(self.events) == 3,
                'Checkpoint duplicated or not after seed pass and main start')
        self.request = {'session': self.session, 'token': self.token, 'nonce': nonce,
                        'line': self.lines, 'name': CHANNEL + '.' + self.session + '.' + nonce,
                        'state': 1}
        return dict(self.request)

    def finish(self):
        require(len(self.events) == 4 and self.request is not None, 'Incomplete combined checkpoint transcript')
        return {'schema_version': 2, 'events': self.events, 'request': self.request,
                'strict_observed_order': True}


def preparation_order(raw):
    """Bind hosted prerequisite then Files preparation to their original log."""
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_LOG, 'Invalid preparation log size')
    prefixes = []
    for test in PREPARATION_TESTS:
        target, cls, method = test.split('/')
        prefixes.append(f"Test Case '-[{target}.{cls} {method}]' ")
    events = []
    for number, line in enumerate(raw.splitlines(), 1):
        require(len(line) <= MAX_LINE and b'\0' not in line, 'Invalid or oversized preparation log line')
        text = line.decode('utf-8', 'strict').removesuffix('\r')
        require(PREFIX not in text, 'Checkpoint cannot occur during preparation')
        matched = False
        for index, prefix in enumerate(prefixes):
            if not text.startswith(prefix): continue
            matched = True
            suffix = text[len(prefix):]
            match = re.fullmatch(r'passed \(((?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,9})?) seconds\)\.', suffix)
            event = 'started' if suffix == 'started.' else 'passed' if match else None
            expected_index, expected_event = divmod(len(events), 2)
            require(event is not None and index == expected_index
                    and event == ('started' if expected_event == 0 else 'passed'),
                    'Preparation cases are failed, malformed, duplicated or out of order')
            if match:
                require(float(match[1]) <= (300, 180)[index], 'Preparation case exceeded its allowance')
            events.append({'case': PREPARATION_CASES[index], 'event': event, 'line': number,
                           'duration_seconds': match[1] if match else None})
            break
        require(matched or not text.startswith("Test Case '-["), 'Unexpected test case in preparation transcript')
    require(len(events) == 4, 'Incomplete preparation transcript')
    return {'schema_version': 2, 'events': events, 'strict_observed_order': True,
            'log': {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}}


def execution_order(raw, session, token):
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_LOG, 'Invalid combined log size')
    parser = Transcript(session, token)
    for line in raw.splitlines(): parser.line(line)
    proof = parser.finish()
    proof['log'] = {'path': 'xcodebuild.log', 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    return proof


def monitor(process, path, deadline, session, token, callback, *, started, now=time.monotonic, sleep=time.sleep):
    """Tail only our own regular append-only file; caller retains process cleanup."""
    parser = Transcript(session, token)
    path = Path(path)
    require(type(started) in (int, float) and math.isfinite(started), 'Invalid second invocation start')
    require(type(deadline) in (int, float) and math.isfinite(deadline) and deadline > started,
            'Invalid original driver deadline')
    pending = b''; total = 0; acknowledged = False; seed_deadline = started+300; native_failed = False; seed_elapsed = None
    def check_clock():
        current = now()
        require(math.isfinite(current) and current >= started, 'Second invocation start is in the future')
        require(current < deadline, 'Original combined driver deadline expired')
        require(seed_deadline is None or current < seed_deadline, 'Seed stage exceeded300s')
        return current
    check_clock()
    first = path.lstat()
    require(stat.S_ISREG(first.st_mode), 'Checkpoint log is not regular')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        while True:
            check_clock()
            current = path.lstat(); opened = os.fstat(fd)
            require((first.st_dev, first.st_ino) == (current.st_dev, current.st_ino)
                    == (opened.st_dev, opened.st_ino)
                    and stat.S_ISREG(current.st_mode) and total <= current.st_size <= MAX_LOG,
                    'Checkpoint log identity/size changed')
            chunk = os.read(fd, 65536)
            if chunk:
                total += len(chunk); pending += chunk
                while b'\n' in pending:
                    check_clock()
                    line, pending = pending.split(b'\n', 1)
                    before = len(parser.events)
                    try:
                        request = None if native_failed else parser.line(line)
                    except NativeCaseFailed:
                        # Preserve normal XCTest finalization and its real failed result.
                        # Never ACK after a failed producer; the UI's own gate fails.
                        native_failed = True; seed_deadline = None; request = None
                    observed = check_clock()
                    if before == 1 and len(parser.events) == 2:
                        seed_elapsed = observed-started; seed_deadline = None
                    if request:
                        require(not acknowledged and process.poll() is None, 'Checkpoint primary is not live')
                        end = min(deadline, now()+TRANSPORT_SECONDS)
                        callback(request, end)
                        require(now() < end, 'Checkpoint callback exceeded transport budget')
                        acknowledged = True
                require(len(pending) <= MAX_LINE, 'Checkpoint line buffer exceeded limit')
                continue
            result = process.poll()
            if result is not None:
                check_clock()
                if pending and not native_failed:
                    try: parser.line(pending)
                    except NativeCaseFailed:
                        native_failed = True; seed_deadline = None
                    check_clock()
                if result == 0:
                    require(not native_failed and acknowledged, 'Combined run had no acknowledged checkpoint')
                    parser.finish()
                final_code = process.wait(timeout=max(0.001, deadline-check_clock()))
                check_clock()
                return {"returncode": final_code,
                        "seed_observed_seconds": seed_elapsed, "seed_envelope_seconds": 300,
                        "seed_started_monotonic": started,
                        "seed_envelope_boundary": "second invocation start to observed seed PASS"}
            sleep(min(0.1, max(0.0, deadline-now())))
    finally:
        os.close(fd)
