#!/usr/bin/env python3
"""One prepare-command supervisor; all children inherit the one owned process group.

No native activity on import. The outer unchanged Recovery Smoke owns this group,
its 600 s command cap, 8 s stop reserve and final group-absence/reap verification.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import struct
import subprocess
import sys
import time

MIB = 1024 ** 2
VIDEO_CAP = 64 * MIB                 # sampled stop threshold, NOT a filesystem quota
LOG_CAP = 4 * MIB                    # hard in-memory read limit; raw text never saved
RECEIPT_CAP = 128 * 1024
MARKER = re.compile(rb'^TD_FILES_COMMIT_V1\|([0-9A-Fa-f-]{36})\|([a-z_]+)\|([0-9]+\.[0-9]+)$')
STAGES = ('start', 'editor_inline', 'editor_alert', 'before_done', 'after_done',
          'postcondition_passed', 'postcondition_failed', 'end')
SOURCE_PREDICATE = ('process == "fileproviderd" OR process == "Files" OR process == "DocumentsApp" '
             'OR process == "testmanagerd" OR subsystem BEGINSWITH "com.apple.FileProvider" '
             'OR subsystem BEGINSWITH "com.apple.DocumentManager"')
VOCABULARY = ('rename', 'commit', 'validation', 'rejected', 'denied', 'failed',
              'error', 'already exists', 'read-only', 'permission', 'cancelled', 'timeout')
# Same retained vocabulary and sources; no extra time or severity scope.
PREDICATE = '(' + SOURCE_PREDICATE + ') AND (' + ' OR '.join(
    'eventMessage CONTAINS[c] "' + word + '"' for word in VOCABULARY) + ')'
EVENT_BYTE_CAP = 256 * 1024
EVENT_DEPTH_CAP = 32
SIGNAL_BYTE_CAP = 64 * 1024


class ObservationError(RuntimeError):
    """Only fixed source-owned codes, never native text, enter receipts."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def reason(error, fallback):
    return error.code if isinstance(error, ObservationError) else fallback


def require(value, message):
    if not value:
        raise RuntimeError(message)


class Markers:
    def __init__(self, uuid):
        self.uuid, self.pending, self.rows = uuid.lower(), b'', []

    def feed(self, chunk, observed):
        self.pending += chunk
        require(len(self.pending) <= 256 * 1024, 'unterminated stdout line cap')
        emitted = []
        while b'\n' in self.pending:
            raw, self.pending = self.pending.split(b'\n', 1)
            match = MARKER.fullmatch(raw.rstrip(b'\r'))
            if not match:
                require(not raw.startswith(b'TD_FILES_COMMIT_V1|'), 'malformed marker')
                continue
            uid, stage, epoch = (part.decode('ascii') for part in match.groups())
            require(uid.lower() == self.uuid and stage in STAGES, 'foreign marker')
            require(stage not in [r['stage'] for r in self.rows], 'duplicate marker')
            seen = [r['stage'] for r in self.rows]
            valid = ((stage == 'start' and not seen)
                     or (stage in ('editor_inline', 'editor_alert') and seen == ['start'])
                     or (stage == 'before_done' and len(seen) == 2 and seen[-1].startswith('editor_'))
                     or (stage == 'after_done' and seen[-1:] == ['before_done'])
                     or (stage.startswith('postcondition_') and seen[-1:] == ['after_done'])
                     or (stage == 'end' and bool(seen)))
            require(valid and 'end' not in seen, 'out-of-order marker')
            value = float(epoch)
            require(0 < value < 4102444800 and (not self.rows or value >= self.rows[-1]['epoch']),
                    'invalid/nonmonotonic marker wall time')
            row = dict(stage=stage, epoch=value, host_observed_monotonic=observed)
            self.rows.append(row); emitted.append(row)
        return emitted

    def finish(self):
        require(not self.pending.startswith(b'TD_FILES_COMMIT_V1|'), 'truncated marker at EOF')


def movie_structure(path):
    """Bounded structural check only; playback/visible boundary still needs review."""
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= VIDEO_CAP, 'movie size/type')
    boxes, offset = [], 0
    with path.open('rb') as stream:
        while offset < info.st_size:
            require(len(boxes) < 4096, 'movie box cap')
            stream.seek(offset); header = stream.read(16)
            require(len(header) >= 8, 'truncated movie box')
            size, kind = struct.unpack('>I4s', header[:8])
            minimum = 8
            if size == 1:
                require(len(header) == 16, 'truncated extended box')
                size = struct.unpack('>Q', header[8:16])[0]; minimum = 16
            elif size == 0:
                size = info.st_size - offset
            require(minimum <= size <= info.st_size-offset, 'invalid movie box')
            boxes.append(kind.decode('ascii', 'replace')); offset += size
    require(all(box in boxes for box in ('ftyp', 'moov', 'mdat')), 'unfinalized movie')
    return dict(bytes=info.st_size, boxes=boxes, playback_verified=False,
                boundary_visibility_verified=False)


def log_time(epoch):
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S+0000')


def reject_json_constant(_):
    raise ObservationError('native_log_invalid_json')


def sanitize_event(event, uuid, begin, finish):
    if not isinstance(event, dict):
        raise ObservationError('native_log_invalid_event')
    message = str(event.get('eventMessage', ''))
    terms = [term for term in VOCABULARY if term in message.lower()]
    if not terms:
        return None, False
    source = str(event.get('subsystem', ''))
    process = Path(str(event.get('processImagePath', ''))).name
    category = ('fileprovider' if source.startswith('com.apple.FileProvider') or process == 'fileproviderd'
                else 'documentmanager' if source.startswith('com.apple.DocumentManager')
                else 'files' if process in ('Files', 'DocumentsApp')
                else 'testmanager' if process == 'testmanagerd' else 'other')
    if category == 'other':
        return None, False
    codes = re.findall(r'\b(?:Code|code)\s*[=:]\s*(-?\d{1,6})\b', message)[:8]
    timestamp = str(event.get('timestamp', ''))
    try:
        parsed = dt.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        require(parsed.tzinfo is not None and begin <= parsed.timestamp() <= finish, 'timestamp outside window')
    except (ValueError, RuntimeError):
        return None, True
    return dict(category=category, timestamp=parsed.isoformat(), terms=terms,
                numeric_codes=codes, error_domains=[domain for domain in
                ('NSCocoaErrorDomain', 'NSPOSIXErrorDomain', 'NSFileProviderErrorDomain', 'NSOSStatusErrorDomain')
                if domain in message], mentions_owned_uuid=uuid.lower() in message.lower()), False


class StreamingLogs:
    """Strict incremental JSON array; retain only complete sanitized objects.

    At most 4 MiB raw input is admitted, 256 KiB for one unfinished event,
    depth 32, and 64 KiB encoded signals inside the unchanged 128 KiB receipt.
    Raw event text is never written to disk. Errors do not resynchronize.
    """
    def __init__(self, uuid, begin, finish):
        self.uuid, self.begin, self.end = uuid, begin, finish
        self.state = 'start'; self.buffer = bytearray()
        self.depth = 0; self.quoted = False; self.escaped = False
        self.admitted_bytes = 0; self.input_event_count = 0
        self.signals = []; self.signal_bytes = 0; self.discarded_timestamp = 0
        self.signals_truncated = False
        self.failure_reason = None

    def feed(self, chunk):
        if self.failure_reason:
            raise ObservationError(self.failure_reason)
        try: self._feed(chunk)
        except ObservationError as error:
            self.failure_reason = error.code
            raise

    def _feed(self, chunk):
        admitted = chunk[:max(0, LOG_CAP-self.admitted_bytes)]
        self.admitted_bytes += len(admitted)
        for char in admitted:
            if self.state == 'event':
                if len(self.buffer) >= EVENT_BYTE_CAP:
                    raise ObservationError('native_log_event_byte_cap')
                self.buffer.append(char)
                if self.quoted:
                    if self.escaped: self.escaped = False
                    elif char == 92: self.escaped = True
                    elif char == 34: self.quoted = False
                elif char == 34: self.quoted = True
                elif char in (123, 91):
                    self.depth += 1
                    if self.depth > EVENT_DEPTH_CAP:
                        raise ObservationError('native_log_depth_cap')
                elif char in (125, 93): self.depth -= 1
                if self.depth == 0:
                    try: event = json.loads(self.buffer.decode('utf-8', 'strict'), parse_constant=reject_json_constant)
                    except (ValueError, UnicodeError, RecursionError):
                        raise ObservationError('native_log_invalid_json') from None
                    self.buffer.clear()
                    self.input_event_count += 1
                    if self.input_event_count > 20000:
                        raise ObservationError('native_log_event_count_cap')
                    row, discarded = sanitize_event(event, self.uuid, self.begin, self.end)
                    self.discarded_timestamp += int(discarded)
                    if row is not None:
                        size = len(json.dumps(row, indent=2).encode()) + 128
                        if len(self.signals) >= 1024 or self.signal_bytes+size > SIGNAL_BYTE_CAP:
                            self.signals_truncated = True
                            raise ObservationError('native_log_signal_cap')
                        self.signals.append(row); self.signal_bytes += size
                    self.state = 'after'
            elif char in b' \r\n\t': continue
            elif self.state == 'start' and char == 91: self.state = 'first'
            elif self.state in ('first', 'next') and char == 123:
                self.state = 'event'; self.buffer.append(char); self.depth = 1
                self.quoted = self.escaped = False
            elif self.state in ('first', 'after') and char == 93: self.state = 'done'
            elif self.state == 'after' and char == 44: self.state = 'next'
            else: raise ObservationError('native_log_invalid_json')
        if len(admitted) != len(chunk):
            raise ObservationError('native_log_byte_cap')

    def finish(self):
        if self.failure_reason: raise ObservationError(self.failure_reason)
        if self.state != 'done':
            self.failure_reason = 'native_log_truncated_json'
            raise ObservationError(self.failure_reason)

    def snapshot(self):
        return dict(input_event_count=self.input_event_count, signals=self.signals,
                    admitted_bytes=self.admitted_bytes, retained_signal_bytes=self.signal_bytes,
                    incomplete_event_bytes=len(self.buffer),
                    signals_truncated=self.signals_truncated,
                    discarded_timestamp=self.discarded_timestamp, raw_text_retained=False,
                    causal_interpretation='unknown; correlated vocabulary is not callback receipt proof')


def sanitize_logs(raw, uuid, begin, finish):
    stream = StreamingLogs(uuid, begin, finish)
    stream.feed(raw); stream.finish()
    return stream.snapshot()


class Supervisor:
    def __init__(self, uuid, token, output, command):
        self.uuid, self.token, self.output, self.command = uuid, token, Path(output), command
        self.started = time.monotonic()
        self.markers = Markers(token)
        self.children = {}; self.selector = selectors.DefaultSelector()
        self.interrupted = False; self.recorder = None; self.record_started = None
        self.video = self.output/'boundary.mp4'
        self.receipt = dict(schema=1, owned_uuid=uuid, run_token=token, group=os.getpgrp(),
                            markers=[], children={}, status='running',
                            video=dict(status='not_started'), native_logs=dict(status='not_started'),
                            original_xcode_returncode=None, commit_callback_received='unknown')
        self.stream_counts = {}
        self.native_discard = False
        self.discard_streams = set()
        self.output.mkdir(mode=0o700)
        self.output_id = self.output.stat().st_dev, self.output.stat().st_ino
        self.save()

    def save(self):
        current = self.output.lstat()
        require(stat.S_ISDIR(current.st_mode) and (current.st_dev,current.st_ino) == self.output_id,
                'observer directory changed')
        self.receipt['markers'] = self.markers.rows
        payload = json.dumps(self.receipt, indent=2).encode()+b'\n'
        require(len(payload) <= RECEIPT_CAP, 'observer receipt cap')
        tmp = self.output/'receipt.tmp'
        with tmp.open('xb') as stream: stream.write(payload)
        tmp.replace(self.output/'receipt.json')

    def spawn(self, name, argv):
        require(name not in self.children and not self.interrupted, 'duplicate/interrupted child')
        if any(row.get('stop_attempted') and not row.get('leader_reaped')
               for row in self.receipt['children'].values()):
            raise ObservationError('child_cleanup_unconfirmed')
        # Intent is durable before acquisition. No new session/group: the existing
        # outer Smoke remains owner of the supervisor and EVERY descendant.
        self.receipt['children'][name] = dict(spawn_attempted=True, pid=None)
        self.save()
        try:
            env = dict(os.environ)
            if name == 'xcode':
                env['TEST_RUNNER_TRIPDOCKET_FILES_COMMIT_OBSERVATION'] = '1'
            child = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     start_new_session=False, close_fds=True, env=env)
        except BaseException:
            self.receipt['children'][name]['spawn_unknown'] = True
            self.interrupted = True
            raise
        self.children[name] = child
        self.receipt['children'][name].update(pid=child.pid, group=os.getpgrp())
        for channel, pipe in (('stdout',child.stdout),('stderr',child.stderr)):
            os.set_blocking(pipe.fileno(),False)
            self.selector.register(pipe, selectors.EVENT_READ, (name,channel))
            self.stream_counts[name,channel] = 0
        self.save()
        return child

    def read(self, delay=.02, native=None):
        for key,_ in self.selector.select(delay):
            name,channel=key.data
            chunk=os.read(key.fd,65536)
            if not chunk:
                self.selector.unregister(key.fileobj); key.fileobj.close(); continue
            self.stream_counts[name,channel] += len(chunk)
            if (name == 'native-log' and self.native_discard) or (name,channel) in self.discard_streams:
                continue
            if name == 'xcode':
                # Retain original output byte-for-byte in the outer bounded streams.
                target=sys.stdout.buffer if channel=='stdout' else sys.stderr.buffer
                target.write(chunk); target.flush()
                if channel=='stdout':
                    for row in self.markers.feed(chunk,time.monotonic()):
                        if row['stage']=='start': self.start_video()
                        self.save()
            elif name=='native-log' and channel=='stdout':
                try:
                    if native is None: raise ObservationError('native_log_missing_sink')
                    native.feed(chunk)
                except BaseException:
                    self.native_discard = True
                    raise
            else:
                # Bounded counters only; do not persist arbitrary native stderr.
                if self.stream_counts[name,channel] > 64*1024:
                    self.discard_streams.add((name,channel))
                    raise ObservationError('diagnostic_stream_byte_cap')

    def start_video(self):
        self.record_started = time.monotonic()
        video = self.receipt['video']
        video.update(status='starting', start_monotonic=self.record_started,
                     sampled_stop_bytes=VIDEO_CAP, hard_filesystem_quota=False,
                     lifecycle_state='spawn_requested', recording_ready_verified=False)
        try:
            self.recorder = self.spawn('recorder',['/usr/bin/xcrun','simctl','io',self.uuid,
                'recordVideo','--codec','h264',str(self.video)])
        except BaseException:
            video.update(status='unavailable', failure_reason='recorder_spawn_failed')
            raise
        video.update(status='recording_requested', lifecycle_state='spawn_returned',
                     running_observed=self.recorder.poll() is None)
        self.save()

    def stop_child(self, name, first=signal.SIGTERM, grace=1.0, native=None):
        child = self.children.get(name)
        if child is None: return
        row = self.receipt['children'][name]
        if name == 'native-log': self.native_discard = True
        if row.get('stop_attempted'):
            row.update(returncode=child.poll(), leader_reaped=child.poll() is not None)
            if not row['leader_reaped']: raise ObservationError('child_unreaped')
            return
        row.update(stop_attempted=True, stop_reason='already_exited',
                   stop_requested_monotonic=time.monotonic(), grace_seconds=grace,
                   signals_semantics='send_wrapper_returned_not_delivery')

        def signal_child(sig):
            row['stop_reason'] = 'forced_stop' if sig == signal.SIGKILL else 'signal_stop'
            try:
                if sig == signal.SIGKILL: child.kill()
                else: child.send_signal(sig)
                row.setdefault('signals', []).append(int(sig))
            except OSError:
                row.setdefault('stop_errors', []).append('child_signal_error')

        def drain_until(end):
            while child.poll() is None and time.monotonic() < end:
                try: self.read(min(.02, max(0, end-time.monotonic())), native)
                except BaseException as error:
                    errors = row.setdefault('drain_errors', [])
                    code = reason(error, 'child_drain_error')
                    if code not in errors and len(errors) < 8: errors.append(code)

        if child.poll() is None:
            signal_child(first)
            drain_until(time.monotonic()+grace)
        if child.poll() is None:
            row['grace_expired'] = True
            signal_child(signal.SIGKILL)
            drain_until(time.monotonic()+.5)
        row.update(returncode=child.poll(), leader_reaped=child.poll() is not None,
                   group_absence_verified_here=False)
        if not row['leader_reaped']:
            row['stop_reason'] = 'child_unreaped'
            raise ObservationError('child_unreaped')

    def stop_video(self):
        if self.recorder is None or self.receipt['video'].get('stop_attempted'): return
        video = self.receipt['video']
        video.update(stop_attempted=True, lifecycle_state='stop_requested',
                     stop_requested_monotonic=time.monotonic(), grace_seconds=1.5)
        video.setdefault('stop_reason', 'xcode_exit')
        early_exit = self.recorder.poll() is not None
        stop_error = None
        try:
            self.stop_child('recorder',signal.SIGINT,1.5)
            video.update(finish_monotonic=time.monotonic(), lifecycle_state='reaped')
            row = self.receipt['children']['recorder']
            if row.get('grace_expired'): raise ObservationError('recorder_forced_stop')
            if row.get('stop_errors') or row.get('drain_errors'):
                raise ObservationError('recorder_stop_error')
            if early_exit: raise ObservationError('recorder_exited_before_stop')
            if self.recorder.returncode != 0: raise ObservationError('recorder_child_failure')
            check = movie_structure(self.video)
            digest = hashlib.sha256()
            with self.video.open('rb') as stream:
                while chunk:=stream.read(MIB): digest.update(chunk)
            video.update(status='structurally_finalized_pending_playback_review',
                         lifecycle_state='structure_checked', sha256=digest.hexdigest(), **check)
        except (RuntimeError,OSError) as error:
            video.update(status='unavailable', error_type=type(error).__name__,
                         failure_reason=reason(error, 'recorder_missing_file' if isinstance(error,FileNotFoundError)
                                               else 'recorder_invalid_structure'))
            if not self.receipt['children']['recorder'].get('leader_reaped'): stop_error = error
        self.save()
        if stop_error is not None: raise stop_error

    def collect_logs(self):
        rows = {r['stage']:r for r in self.markers.rows}
        if 'before_done' not in rows or self.interrupted:
            self.receipt['native_logs'] = dict(status='unavailable', complete=False,
                stop_reason='native_log_interrupted' if self.interrupted else 'native_log_no_boundary')
            return
        begin = rows['before_done']['epoch']-2
        finish = next((rows[s]['epoch']+2 for s in ('postcondition_failed','postcondition_passed','end') if s in rows),begin+120)
        finish = min(finish,begin+124)
        self.receipt['native_logs'] = dict(status='querying', complete=False, start_epoch=begin,end_epoch=finish)
        stream = StreamingLogs(self.token, begin, finish)
        failure = None; error_type = None; stop_error = None
        try:
            child = self.spawn('native-log',['/usr/bin/xcrun','simctl','spawn',self.uuid,'log','show',
                '--style','json','--info','--debug','--start',log_time(begin),'--end',log_time(finish),
                '--predicate',PREDICATE])
            end = time.monotonic()+18
            while child.poll() is None or any(k.data[0]=='native-log' for k in self.selector.get_map().values()):
                if self.interrupted: raise ObservationError('native_log_interrupted')
                if time.monotonic() >= end: raise ObservationError('native_log_time_cap')
                self.read(.02,stream)
            if child.returncode != 0: raise ObservationError('native_log_child_failure')
            stream.finish()
        except BaseException as error:
            failure = reason(error, 'native_log_error'); error_type = type(error).__name__
        finally:
            self.native_discard = True
            try:
                self.stop_child('native-log')
                row = self.receipt['children'].get('native-log', {})
                if row.get('stop_errors') or row.get('drain_errors'):
                    failure = failure or 'native_log_stop_error'
            except BaseException as error:
                failure = failure or reason(error, 'native_log_stop_error')
                error_type = error_type or type(error).__name__; stop_error = error
            summary = stream.snapshot(); stream.buffer.clear()
            self.receipt['native_logs'].update(summary,
                status='partial' if failure else 'sanitized', complete=failure is None,
                stop_reason=failure or 'eof', error_type=error_type,
                discarded_raw_bytes=max(0,self.stream_counts.get(('native-log','stdout'),0)-stream.admitted_bytes))
            self.save()
        if stop_error is not None: raise stop_error

    def run(self):
        xcode=None;failure=None;failure_reason=None
        try:
            xcode=self.spawn('xcode',self.command)
            while xcode.poll() is None or any(k.data[0]=='xcode' for k in self.selector.get_map().values()):
                require(not self.interrupted,'interrupted')
                self.read()
                if self.recorder is not None and not self.receipt['video'].get('stop_attempted'):
                    stages=[r['stage'] for r in self.markers.rows]
                    timed=time.monotonic()-self.record_started>=120
                    oversized=self.video.exists() and self.video.lstat().st_size>=VIDEO_CAP
                    if timed or oversized or any(s.startswith('postcondition_') or s=='end' for s in stages):
                        self.receipt['video']['stop_reason']='byte_cap' if oversized else 'duration_cap' if timed else 'boundary'
                        self.stop_video()
            self.receipt['original_xcode_returncode']=xcode.returncode
            self.markers.finish()
            self.stop_video()
            self.collect_logs()
        except BaseException as error:
            failure=type(error).__name__; failure_reason=reason(error, 'observer_interrupted' if self.interrupted else 'observer_error')
        finally:
            # All direct children are stopped before leader exit. The UNCHANGED
            # outer Smoke additionally verifies absence of the entire group.
            if self.recorder is not None and not self.receipt['video'].get('stop_attempted'):
                self.receipt['video']['stop_reason']='parent_interrupted' if self.interrupted else 'observer_error'
                try: self.stop_video()
                except BaseException as error:
                    failure=failure or type(error).__name__
                    failure_reason=failure_reason or reason(error, 'observer_cleanup_error')
            for name in ('recorder','native-log','xcode'):
                try:self.stop_child(name, signal.SIGINT if name=='recorder' else signal.SIGTERM)
                except BaseException as error:
                    failure=failure or type(error).__name__
                    failure_reason=failure_reason or reason(error, 'observer_cleanup_error')
            if xcode is not None:self.receipt['original_xcode_returncode']=xcode.poll()
            for key in list(self.selector.get_map().values()):
                self.selector.unregister(key.fileobj);key.fileobj.close()
            self.selector.close()
            stages=[r['stage'] for r in self.markers.rows]
            self.receipt['boundary_markers_complete']=('editor_inline' in stages and 'before_done' in stages
                    and 'after_done' in stages and any(s.startswith('postcondition_') for s in stages))
            self.receipt['result_inconsistent']=(self.receipt['original_xcode_returncode']==0 and 'postcondition_failed' in stages)
            self.receipt.update(status='finished' if failure is None else 'observer_failed',error_type=failure,
                                stop_reason=failure_reason or 'completed',
                                elapsed_seconds=time.monotonic()-self.started,
                                stream_bytes={a+'/'+b:n for (a,b),n in self.stream_counts.items()})
            self.save()
        code=self.receipt['original_xcode_returncode']
        # Preserve the original failure. A failed observer cannot turn a UI
        # failure into success; successful UI with unavailable evidence fails closed.
        return (code if isinstance(code,int) and code!=0 else
                0 if failure is None and self.receipt['boundary_markers_complete']
                and 'postcondition_passed' in [r['stage'] for r in self.markers.rows]
                and self.receipt['video']['status']=='structurally_finalized_pending_playback_review'
                and self.receipt['native_logs']['status']=='sanitized'
                and self.receipt['native_logs'].get('complete') is True else 70)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owned-uuid',required=True);parser.add_argument('--run-token',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args(argv)
    require(re.fullmatch(r'[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}',args.owned_uuid),'invalid owned UUID')
    command=args.command[1:] if args.command[:1]==['--'] else args.command
    require(command and Path(command[0]).name=='xcodebuild' and command[-1]=='test','invalid prepare command')
    require([arg for arg in command if arg.startswith('-only-testing:')]==
            ['-only-testing:TripfolioUITests/BatchImportUITests/testRecoveryCreateOwnedFilesDestination'], 'wrong selected case')
    for flag,value in (('-destination','platform=iOS Simulator,id='+args.owned_uuid),
                       ('-default-test-execution-time-allowance','120'),
                       ('-maximum-test-execution-time-allowance','120'),
                       ('-parallel-testing-enabled','NO')):
        require(command.count(flag)==1 and command.index(flag)+1<len(command)
                and command[command.index(flag)+1]==value, 'unexpected prepare argument')
    require(os.getpid()==os.getpgrp(),'supervisor must be the one outer-owned group leader')
    require(re.fullmatch(r'[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}',args.run_token),'invalid run token')
    supervisor=Supervisor(args.owned_uuid,args.run_token,args.output,command)
    previous={sig:signal.signal(sig,lambda *_:setattr(supervisor,'interrupted',True)) for sig in (signal.SIGINT,signal.SIGTERM)}
    try:return supervisor.run()
    finally:
        for sig,handler in previous.items():signal.signal(sig,handler)


if __name__=='__main__':sys.exit(main())
