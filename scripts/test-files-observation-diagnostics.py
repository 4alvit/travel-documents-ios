"""Synthetic parser/lifecycle regressions; never starts an Apple/native child."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

MODULE = Path(os.environ.get('OBSERVER_MODULE', Path(__file__).with_name('files_commit_observer.py')))
spec = importlib.util.spec_from_file_location('diagnostic_observer', MODULE)
o = importlib.util.module_from_spec(spec)
with patch('subprocess.Popen', side_effect=AssertionError('native spawn forbidden')):
    spec.loader.exec_module(o)
TOKEN = '11111111-1111-4111-8111-111111111111'
DEVICE = '22222222-2222-4222-8222-222222222222'


def event():
    return dict(eventMessage='rename commit rejected NSCocoaErrorDomain Code=4 ' + TOKEN +
                ' private@example.test /Users/private/passport.pdf \\" café 🧳 {[]}',
                subsystem='com.apple.FileProvider', processImagePath='/private/fileproviderd',
                timestamp='1970-01-01 00:01:42+0000', nested={'x': ['[]', {'y': 1}]})


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode()


class Base(unittest.TestCase):
    def setUp(self):
        self.no_native = patch('subprocess.Popen', side_effect=AssertionError('native spawn forbidden'))
        self.no_native.start()
        self.addCleanup(self.no_native.stop)

    def supervisor(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        s = o.Supervisor(DEVICE, TOKEN, Path(temp.name)/'obs', [])
        self.addCleanup(s.selector.close)
        s.markers.rows = [{'stage': 'before_done', 'epoch': 100},
                          {'stage': 'postcondition_failed', 'epoch': 116}]
        return s


class StreamingTests(Base):
    def test_every_split_and_bytewise_utf8_quotes_nested(self):
        raw = encoded([event(), event()])
        expected = o.sanitize_logs(raw, TOKEN, 100, 116)
        for cut in range(len(raw)+1):
            s = o.StreamingLogs(TOKEN, 100, 116)
            s.feed(raw[:cut]); s.feed(raw[cut:]); s.finish()
            self.assertEqual(s.snapshot(), expected)
        s = o.StreamingLogs(TOKEN, 100, 116)
        for byte in raw: s.feed(bytes([byte]))
        s.finish(); self.assertEqual(s.snapshot(), expected)

    def test_bad_suffix_never_resynchronizes_or_discards_good_prefix(self):
        first = encoded(event())
        for suffix in (b',]', b' {}]', b',BROKEN,'+first+b']', b'] trailing'):
            s = o.StreamingLogs(TOKEN, 100, 116)
            with self.assertRaises(RuntimeError): s.feed(b'['+first+suffix)
            self.assertEqual(len(s.signals), 1)
            with self.assertRaises(RuntimeError): s.feed(b']')
            with self.assertRaises(RuntimeError): s.finish()

    def test_invalid_utf8_and_non_json_constants_retain_only_good_prefix(self):
        for bad in (b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}',
                    b'{"eventMessage":"\xed\xa0\x80"}'):
            s = o.StreamingLogs(TOKEN, 100, 116)
            with self.assertRaisesRegex(RuntimeError, 'native_log_invalid_json'):
                s.feed(b'['+encoded(event())+b','+bad+b']')
            self.assertEqual(len(s.signals), 1)
            with self.assertRaises(RuntimeError): s.feed(b'[]')
            with self.assertRaises(RuntimeError): s.finish()

    def test_incomplete_last_object_keeps_first(self):
        s = o.StreamingLogs(TOKEN, 100, 116)
        s.feed(b'['+encoded(event())+b',{"eventMessage":"private')
        with self.assertRaisesRegex(RuntimeError, 'truncated'): s.finish()
        self.assertEqual(len(s.signals), 1)

    def test_crossing_byte_cap_processes_only_allowed_prefix(self):
        first = b'['+encoded(event())
        for cap in (len(first), len(first)+4):
            s = o.StreamingLogs(TOKEN, 100, 116)
            with patch.object(o, 'LOG_CAP', cap):
                with self.assertRaisesRegex(RuntimeError, 'native_log_byte_cap'):
                    s.feed(first+b',{"eventMessage":"oversized"}]')
            self.assertEqual(s.admitted_bytes, cap)
            self.assertEqual(len(s.signals), 1)

    def test_object_depth_and_object_bytes_are_bounded(self):
        cases = [(b'['+b'{"x":'*40, 'depth_cap'),
                 (b'[{"x":"'+b'a'*(o.EVENT_BYTE_CAP+1), 'event_byte_cap')]
        for raw, message in cases:
            s = o.StreamingLogs(TOKEN, 100, 116)
            with self.assertRaisesRegex(RuntimeError, message): s.feed(raw)
            self.assertLessEqual(len(s.buffer), o.EVENT_BYTE_CAP)

    def test_retention_cap_keeps_prefix_and_bounds_encoded_receipt(self):
        s = o.StreamingLogs(TOKEN, 100, 116)
        with self.assertRaisesRegex(RuntimeError, 'signal_cap'):
            s.feed(encoded([event()]*1025))
        self.assertTrue(s.signals_truncated)
        self.assertGreater(len(s.signals), 0)
        self.assertLessEqual(s.signal_bytes, o.SIGNAL_BYTE_CAP)
        self.assertLess(len(json.dumps(s.snapshot(), indent=2).encode()), o.RECEIPT_CAP)

    def test_empty_whitespace_and_top_level_shape(self):
        s = o.StreamingLogs(TOKEN, 100, 116); s.feed(b' \n[ ]\t'); s.finish()
        self.assertEqual(s.signals, [])
        for raw in (b'{}', b'[1]', b'[[]]', b'[null]'):
            with self.assertRaises(RuntimeError): o.sanitize_logs(raw, TOKEN, 100, 116)

    def test_no_private_text_in_retained_prefix_or_failure_reason(self):
        s = o.StreamingLogs(TOKEN, 100, 116)
        with self.assertRaises(RuntimeError): s.feed(b'['+encoded(event())+b'] private@example.test')
        text = json.dumps(s.snapshot()) + s.failure_reason
        for private in ('private@example', '/Users/', 'passport.pdf', TOKEN, 'café'):
            self.assertNotIn(private, text)
        self.assertIn('unknown', text)

    def test_predicate_only_narrows_original_sources_with_same_vocabulary(self):
        self.assertTrue(o.PREDICATE.startswith('('+o.SOURCE_PREDICATE+') AND ('))
        for word in o.VOCABULARY:
            self.assertIn('eventMessage CONTAINS[c] "'+word+'"', o.PREDICATE)


class LifecycleTests(Base):
    def child(self, s, name, exit_on_signal=False, never_reap=False):
        state = [None]; sent = []
        class Child:
            @property
            def returncode(self): return state[0]
            def poll(self): return state[0]
            def send_signal(self, sig):
                sent.append(int(sig))
                if exit_on_signal: state[0] = 0
            def kill(self):
                sent.append(9)
                if not never_reap: state[0] = -9
        child = Child(); s.children[name] = child; s.receipt['children'][name] = {}
        return child, state, sent

    def ticking_read(self, s, exception=None):
        clock = [0.0]
        def read(delay=.02, native=None):
            clock[0] += max(delay, .01)
            if exception: raise exception
        return clock, read

    def test_drain_exception_cannot_prevent_kill_reap(self):
        s = self.supervisor(); child, state, sent = self.child(s, 'native-log')
        clock, read = self.ticking_read(s, RuntimeError('private@example.test'))
        with patch.object(s, 'read', side_effect=read), patch.object(o.time, 'monotonic', side_effect=lambda: clock[0]):
            s.stop_child('native-log')
        self.assertEqual(sent, [15, 9]); self.assertTrue(s.receipt['children']['native-log']['leader_reaped'])
        self.assertNotIn('private@example', json.dumps(s.receipt))

    def test_stop_is_idempotent_even_when_reap_unconfirmed(self):
        s = self.supervisor(); child, state, sent = self.child(s, 'recorder', never_reap=True)
        clock, read = self.ticking_read(s)
        with patch.object(s, 'read', side_effect=read), patch.object(o.time, 'monotonic', side_effect=lambda: clock[0]):
            for _ in range(2):
                with self.assertRaises(RuntimeError): s.stop_child('recorder', signal.SIGINT, 1.5)
        self.assertEqual(sent, [2, 9]); self.assertLessEqual(clock[0], 2.03)
        with self.assertRaisesRegex(RuntimeError, 'cleanup_unconfirmed'): s.spawn('native-log', ['forbidden'])

    def test_actual_overflow_read_enters_discard_before_cleanup(self):
        s = self.supervisor(); child, state, sent = self.child(s, 'native-log')
        rfd, wfd = os.pipe(); stream = os.fdopen(rfd, 'rb', buffering=0)
        self.addCleanup(lambda: stream.close() if not stream.closed else None)
        os.set_blocking(rfd, False); s.selector.register(stream, o.selectors.EVENT_READ, ('native-log', 'stdout'))
        s.stream_counts['native-log', 'stdout'] = 0
        raw = b'['+encoded(event())+b' '*100
        os.write(wfd, raw); os.close(wfd)
        parser = o.StreamingLogs(TOKEN, 100, 116)
        with patch.object(o, 'LOG_CAP', len(raw)-50):
            with self.assertRaises(RuntimeError): s.read(.01, parser)
        self.assertTrue(s.native_discard)
        self.assertEqual(len(parser.signals), 1)
        s.read(.01, None)  # EOF/discard does not need a parser or throw again.
        clock, read = self.ticking_read(s)
        with patch.object(s, 'read', side_effect=read), patch.object(o.time, 'monotonic', side_effect=lambda: clock[0]):
            s.stop_child('native-log')
        self.assertEqual(sent, [15, 9])

    def test_forced_recorder_stop_has_specific_reason_and_no_repeat(self):
        s = self.supervisor(); child, state, sent = self.child(s, 'recorder'); s.recorder = child
        clock, read = self.ticking_read(s)
        with patch.object(s, 'read', side_effect=read), patch.object(o.time, 'monotonic', side_effect=lambda: clock[0]):
            s.stop_video(); s.stop_video(); s.stop_child('recorder', signal.SIGINT, 1.5)
        self.assertEqual(sent, [2, 9]); self.assertEqual(s.receipt['video']['failure_reason'], 'recorder_forced_stop')

    def test_polite_recorder_finalization_preserves_no_playback_claim(self):
        s = self.supervisor(); child, state, sent = self.child(s, 'recorder', exit_on_signal=True); s.recorder = child
        s.video.write_bytes(b''.join(struct.pack('>I4s', 8, x) for x in (b'ftyp', b'mdat', b'moov')))
        s.stop_video()
        self.assertEqual(sent, [2]); self.assertFalse(s.receipt['video']['playback_verified'])
        self.assertEqual(s.receipt['video']['lifecycle_state'], 'structure_checked')

    def collect_fixture(self, mode):
        s = self.supervisor(); child, state, sent = self.child(s, 'native-log', exit_on_signal=True)
        clock = [0.0]; reads = [0]
        def read(delay=.02, native=None):
            reads[0] += 1
            if reads[0] == 1:
                if mode == 'cap':
                    with patch.object(o, 'LOG_CAP', len(encoded(event()))+1):
                        native.feed(b'['+encoded(event())+b',{}]')
                native.feed(encoded([event()]) if mode in ('success', 'child') else b'['+encoded(event()))
            if mode == 'timeout': clock[0] = 18.0
            elif mode == 'interrupt': s.interrupted = True
            elif mode == 'malformed': native.feed(b' BAD')
            elif mode == 'invalid_constant': native.feed(b',{"x":NaN}]')
            elif mode == 'invalid_utf8': native.feed(b',{"x":\"\xed\xa0\x80\"}]')
            else: state[0] = 65 if mode == 'child' else 0
        with patch.object(s, 'spawn', return_value=child), patch.object(s, 'read', side_effect=read), patch.object(o.time, 'monotonic', side_effect=lambda: clock[0]):
            s.collect_logs()
        return s.receipt['native_logs']

    def test_complete_only_after_closed_array_eof_and_success(self):
        row = self.collect_fixture('success')
        self.assertTrue(row['complete']); self.assertEqual(row['status'], 'sanitized')
        self.assertEqual(row['stop_reason'], 'eof')

    def test_caps_timeout_interruption_malformed_and_child_failure_retain_partial(self):
        cases = [('cap', 'native_log_byte_cap'), ('timeout', 'native_log_time_cap'),
                 ('interrupt', 'native_log_interrupted'), ('malformed', 'native_log_invalid_json'),
                 ('child', 'native_log_child_failure'), ('invalid_constant', 'native_log_invalid_json'),
                 ('invalid_utf8', 'native_log_invalid_json')]
        for mode, reason in cases:
            with self.subTest(mode=mode):
                row = self.collect_fixture(mode)
                self.assertFalse(row['complete']); self.assertEqual(row['status'], 'partial')
                self.assertEqual(row['stop_reason'], reason); self.assertEqual(len(row['signals']), 1)


if __name__ == '__main__': unittest.main()
