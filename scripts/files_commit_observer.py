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
PREDICATE = ('process == "fileproviderd" OR process == "Files" OR process == "DocumentsApp" '
             'OR process == "testmanagerd" OR subsystem BEGINSWITH "com.apple.FileProvider" '
             'OR subsystem BEGINSWITH "com.apple.DocumentManager"')


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


def sanitize_logs(raw, uuid, begin, finish):
    """Return closed-vocabulary signals, never event text, paths or arbitrary IDs."""
    require(len(raw) <= LOG_CAP, 'native log cap')
    events = json.loads(raw)
    require(isinstance(events, list) and len(events) <= 20000, 'native log event shape/cap')
    result = []; discarded_timestamp = 0
    vocabulary = ('rename', 'commit', 'validation', 'rejected', 'denied', 'failed',
                  'error', 'already exists', 'read-only', 'permission', 'cancelled', 'timeout')
    for event in events:
        require(isinstance(event, dict), 'invalid native log event')
        message = str(event.get('eventMessage', ''))
        terms = [term for term in vocabulary if term in message.lower()]
        if not terms:
            continue
        source = str(event.get('subsystem', ''))
        process = Path(str(event.get('processImagePath', ''))).name
        category = ('fileprovider' if source.startswith('com.apple.FileProvider') or process == 'fileproviderd'
                    else 'documentmanager' if source.startswith('com.apple.DocumentManager')
                    else 'files' if process in ('Files', 'DocumentsApp')
                    else 'testmanager' if process == 'testmanagerd' else 'other')
        if category == 'other':
            continue
        codes = re.findall(r'\b(?:Code|code)\s*[=:]\s*(-?\d{1,6})\b', message)[:8]
        timestamp = str(event.get('timestamp', ''))
        try:
            parsed=dt.datetime.fromisoformat(timestamp.replace('Z','+00:00'))
            require(parsed.tzinfo is not None and begin <= parsed.timestamp() <= finish, 'timestamp outside window')
            timestamp=parsed.isoformat()
        except (ValueError, RuntimeError):
            discarded_timestamp+=1
            continue
        result.append(dict(category=category, timestamp=timestamp, terms=terms,
                           numeric_codes=codes, error_domains=[domain for domain in
                           ('NSCocoaErrorDomain','NSPOSIXErrorDomain','NSFileProviderErrorDomain','NSOSStatusErrorDomain')
                           if domain in message], mentions_owned_uuid=uuid.lower() in message.lower()))
        require(len(result) <= 1024, 'retained native log event cap')
    return dict(input_event_count=len(events), signals=result, discarded_timestamp=discarded_timestamp, raw_text_retained=False,
                causal_interpretation='unknown; correlated vocabulary is not callback receipt proof')


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
            if name == 'xcode':
                # Retain original output byte-for-byte in the outer bounded streams.
                target=sys.stdout.buffer if channel=='stdout' else sys.stderr.buffer
                target.write(chunk); target.flush()
                if channel=='stdout':
                    for row in self.markers.feed(chunk,time.monotonic()):
                        if row['stage']=='start': self.start_video()
                        self.save()
            elif name=='native-log' and channel=='stdout':
                require(native is not None and len(native)+len(chunk)<=LOG_CAP,'native log cap')
                native.extend(chunk)
            else:
                # Bounded counters only; do not persist arbitrary native stderr.
                require(self.stream_counts[name,channel] <= 64*1024,'native diagnostic stream cap')

    def start_video(self):
        self.record_started=time.monotonic()
        self.receipt['video'].update(status='starting',start_monotonic=self.record_started,
                                      sampled_stop_bytes=VIDEO_CAP,hard_filesystem_quota=False)
        self.recorder=self.spawn('recorder',['/usr/bin/xcrun','simctl','io',self.uuid,
                                            'recordVideo','--codec','h264',str(self.video)])
        self.receipt['video']['status']='recording_requested'
        self.save()

    def stop_child(self, name, first=signal.SIGTERM, grace=1.0, native=None):
        child=self.children.get(name)
        if child is None:return
        row=self.receipt['children'][name]
        if child.poll() is None:
            child.send_signal(first);row.setdefault('signals',[]).append(int(first))
        end=time.monotonic()+grace
        while child.poll() is None and time.monotonic()<end:
            self.read(min(.02,max(0,end-time.monotonic())),native)
        if child.poll() is None:
            child.kill();row.setdefault('signals',[]).append(int(signal.SIGKILL))
            end=time.monotonic()+.5
            while child.poll() is None and time.monotonic()<end:
                self.read(.01,native)
        row.update(returncode=child.poll(),leader_reaped=child.poll() is not None,
                   group_absence_verified_here=False)
        require(row['leader_reaped'],'child did not reap; outer group cleanup required')

    def stop_video(self):
        if self.recorder is None or self.receipt['video'].get('stop_attempted'):return
        self.receipt['video']['stop_attempted']=True
        self.stop_child('recorder',signal.SIGINT,1.5)
        self.receipt['video']['finish_monotonic']=time.monotonic()
        try:
            require(self.recorder.returncode == 0 and int(signal.SIGKILL) not in self.receipt['children']['recorder'].get('signals',[]),
                    'recorder did not finalize normally')
            check=movie_structure(self.video)
            digest=hashlib.sha256()
            with self.video.open('rb') as stream:
                while chunk:=stream.read(MIB):digest.update(chunk)
            self.receipt['video'].update(status='structurally_finalized_pending_playback_review',
                                         sha256=digest.hexdigest(),**check)
        except (RuntimeError,OSError) as error:
            self.receipt['video'].update(status='unavailable',error_type=type(error).__name__)
        self.save()

    def collect_logs(self):
        rows={r['stage']:r for r in self.markers.rows}
        if 'before_done' not in rows or self.interrupted:
            self.receipt['native_logs']={'status':'unavailable_no_boundary_or_interrupted'};return
        begin=rows['before_done']['epoch']-2
        finish=next((rows[s]['epoch']+2 for s in ('postcondition_failed','postcondition_passed','end') if s in rows),begin+120)
        finish=min(finish,begin+124)
        self.receipt['native_logs']=dict(status='querying',start_epoch=begin,end_epoch=finish)
        raw=bytearray()
        child=self.spawn('native-log',['/usr/bin/xcrun','simctl','spawn',self.uuid,'log','show',
                        '--style','json','--info','--debug','--start',log_time(begin),'--end',log_time(finish),
                        '--predicate',PREDICATE])
        end=time.monotonic()+18
        try:
            while child.poll() is None or any(k.data[0]=='native-log' for k in self.selector.get_map().values()):
                require(not self.interrupted and time.monotonic()<end,'native log timeout')
                self.read(.02,raw)
            require(child.returncode==0,'native log failed')
            self.receipt['native_logs'].update(status='sanitized',**sanitize_logs(raw,self.token,begin,finish))
        except (RuntimeError,ValueError) as error:
            self.receipt['native_logs'].update(status='unavailable',error_type=type(error).__name__)
        finally:
            self.stop_child('native-log',native=raw)
            raw.clear()
            self.save()

    def run(self):
        xcode=None;failure=None
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
                        self.receipt['video']['stop_reason']='size' if oversized else 'duration' if timed else 'boundary'
                        self.stop_video()
            self.receipt['original_xcode_returncode']=xcode.returncode
            self.markers.finish()
            self.stop_video()
            self.collect_logs()
        except BaseException as error:
            failure=type(error).__name__
        finally:
            # All direct children are stopped before leader exit. The UNCHANGED
            # outer Smoke additionally verifies absence of the entire group.
            for name in ('recorder','native-log','xcode'):
                try:self.stop_child(name, signal.SIGINT if name=='recorder' else signal.SIGTERM)
                except BaseException as error:failure=failure or type(error).__name__
            if xcode is not None:self.receipt['original_xcode_returncode']=xcode.poll()
            for key in list(self.selector.get_map().values()):
                self.selector.unregister(key.fileobj);key.fileobj.close()
            self.selector.close()
            stages=[r['stage'] for r in self.markers.rows]
            self.receipt['boundary_markers_complete']=('editor_inline' in stages and 'before_done' in stages
                    and 'after_done' in stages and any(s.startswith('postcondition_') for s in stages))
            self.receipt['result_inconsistent']=(self.receipt['original_xcode_returncode']==0 and 'postcondition_failed' in stages)
            self.receipt.update(status='finished' if failure is None else 'observer_failed',error_type=failure,
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
                and self.receipt['native_logs']['status']=='sanitized' else 70)


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
