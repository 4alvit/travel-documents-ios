"""Owned-process primitives derived from functional-v1, with bounded diagnostics."""
import errno
import json
import os
import select
import signal
import subprocess
import time
import uuid

PER_LOG, ALL_LOG = 16 * 1024**2, 64 * 1024**2

def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def observed(runner, record, stage, operation, call):
    """Summarize existing calls in six fixed slots; never probe or persist here."""
    started = runner.ops.now() - runner.t0
    slots = record.setdefault('process_observations', {})
    row = slots.setdefault(stage + '.' + operation,
                           {'calls': 0, 'first_start': started})
    row['calls'] += 1
    row['last_start'] = started
    try:
        result = call()
        row.update(outcome='returned', result=result)
        return result
    except BaseException as error:
        row.pop('result', None)
        row.update(outcome='raised', exception_type=type(error).__name__,
                   errno=getattr(error, 'errno', None))
        raise
    finally:
        row['last_finish'] = runner.ops.now() - runner.t0
        row['last_duration'] = row['last_finish'] - started


class RealOps:
    """Thin OS boundary, never constructed by import or default CLI."""
    now = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)

    def __init__(self, env, cwd):
        self.env, self.cwd = env, cwd

    def spawn(self, argv):
        p = subprocess.Popen(argv, cwd=self.cwd, env=self.env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, start_new_session=True)
        return p

    def prepare(self, p):
        for f in (p.stdout, p.stderr):
            os.set_blocking(f.fileno(), False)

    def read(self, p):
        result = []
        for name, stream in (('stdout', p.stdout), ('stderr', p.stderr)):
            if select.select([stream], [], [], 0)[0]:
                chunk = os.read(stream.fileno(), 65536)
                if chunk:
                    result.append((name, chunk))
        return result

    def absent(self, p):
        try:
            os.killpg(p.pid, 0)
        except ProcessLookupError as error:
            if error.errno != errno.ESRCH:
                raise
            return True
        return False  # PermissionError deliberately propagates.

    def send(self, p, sig):
        try:
            os.killpg(p.pid, sig)
        except ProcessLookupError as error:
            if error.errno != errno.ESRCH:
                raise
            return 'already_absent_ESRCH'
        # A successful syscall return does not establish delivery or termination.
        return 'syscall_returned'

    def close(self, p):
        p.stdout.close()
        p.stderr.close()


class Smoke:
    def error(self, error):
        self.report['errors'].append(str(error))

    def save(self):
        require(self.ops.now() < self.write_deadline, 'Final receipt deadline reached')
        self.report['elapsed_seconds'] = self.ops.now() - self.t0
        tmp = self.out / 'receipt.tmp'
        tmp.write_text(json.dumps(self.report, indent=2) + '\n')
        tmp.replace(self.out / 'receipt.json')
        require(self.ops.now() < self.write_deadline, 'Receipt write exceeded final deadline')

    def signal(self, *_):
        self.interrupted = True  # Defer delivery until spawn/acquisition bookkeeping finishes.

    def pump(self, p, record, handles):
        for channel, chunk in self.ops.read(p):
            room = min(PER_LOG - record['bytes'][channel], ALL_LOG - self.log_total)
            accepted = chunk[:max(0, room)]
            handles[channel].write(accepted)
            record['bytes'][channel] += len(accepted)
            self.log_total += len(accepted)
            require(len(accepted) == len(chunk), 'Output cap exceeded')
        self.checkpoint()

    def stop(self, p, deadline, record):
        require(self.active.get(p.pid) is p, 'Unowned group')
        stop = record.setdefault('stop', {'signals': [], 'group_absent': False, 'leader_reaped': False})
        require(not stop.get('attempted'), 'No repeated signalling after stop attempt')
        stop['attempted'] = True
        stop['signals_semantics'] = 'send_wrapper_returned_not_delivery'
        try:
            def done():
                stop['leader_reaped'] = observed(self, record, 'stop', 'poll', p.poll) is not None
                if p.pid in self.absent_groups or observed(
                        self, record, 'stop', 'group_probe', lambda: self.ops.absent(p)):
                    self.absent_groups.add(p.pid)
                    stop['group_absent'] = True
                return stop['leader_reaped'] and stop['group_absent']
            if not done():
                for sig, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, 2)):
                    require(self.ops.now() < deadline, 'Stop deadline reached')
                    if not stop['group_absent']:
                        observed(self, record, 'stop', 'signal_' + str(int(sig)),
                                 lambda: self.ops.send(p, sig))
                        stop['signals'].append(int(sig))
                    end = min(deadline, self.ops.now() + grace)
                    while not done() and self.ops.now() < end:
                        self.ops.sleep(min(.05, end - self.ops.now()))
                    if done():
                        break
            require(done(), 'Group absence/reap unconfirmed')
            self.active.pop(p.pid)
        except BaseException as error:
            stop['error'] = repr(error)
            raise

    def command(self, label, argv, cap):
        self.checkpoint()
        require(not self.active and not self.unknown_spawn, 'Prior process ownership unresolved; further process creation withheld')
        end = min(self.limit, self.ops.now() + cap)
        require(end - self.ops.now() > 8, 'Insufficient command/stop budget')
        record = {'id': label, 'argv': argv, 'bytes': {'stdout': 0, 'stderr': 0}, 'start': self.ops.now() - self.t0,
                  'requested_cap_seconds': cap, 'stop_reserve_seconds': 8,
                  'work_deadline': end - 8 - self.t0, 'command_deadline': end - self.t0}
        self.report['commands'].append(record)
        self.save()  # Intent and any one-shot counter are durable before spawn.
        p, failure = None, None
        paths = {k: self.out / (str(len(self.report['commands'])) + '-' + k + '.log') for k in ('stdout', 'stderr')}
        record['logs'] = {k: str(v) for k, v in paths.items()}
        handles = {k: v.open('wb') for k, v in paths.items()}
        try:
            try:
                p = self.ops.spawn(argv)
            except BaseException:
                self.unknown_spawn = True
                raise
            if p.pid <= 0 or p.pid in self.active:
                self.unknown_spawn = True
                raise RuntimeError('Invalid/colliding PID')
            self.absent_groups.discard(p.pid)
            self.active[p.pid] = p
            record['pgid'] = p.pid
            self.ops.prepare(p)
            self.save()
            while True:
                self.pump(p, record, handles)
                if observed(self, record, 'command', 'poll', p.poll) is not None:
                    # Drain bounded pipe output after leader exit; deadline still applies.
                    before = sum(record['bytes'].values())
                    self.pump(p, record, handles)
                    if sum(record['bytes'].values()) == before:
                        break
                require(self.ops.now() < end - 8, 'Command timeout')
                self.ops.sleep(min(.02, max(0, end - 8 - self.ops.now())))
            record['returncode'] = p.returncode
            require(observed(self, record, 'command', 'group_probe', lambda: self.ops.absent(p)),
                    'Leader exited but process group remains')
            self.absent_groups.add(p.pid)
            require(p.returncode == 0, 'Nonzero command exit: ' + str(p.returncode))
        except BaseException as error:
            failure = error
            record['error'] = repr(error)
        finally:
            if p is not None and self.active.get(p.pid) is p:
                try:
                    self.stop(p, min(end, self.limit), record)
                except BaseException as error:
                    failure = failure or error
                    record['stop_error'] = repr(error)
                try:
                    self.ops.close(p)
                except BaseException as error:
                    failure = failure or error
                    record['close_error'] = repr(error)
            for f in handles.values():
                f.close()
            record['finish'] = self.ops.now() - self.t0
            self.save()
            if self.ops.now() > end:
                failure = failure or RuntimeError('Command plus cleanup exceeded cap')
        if failure:
            self.error(label + ': ' + repr(failure))
            raise RuntimeError(label + ' failed') from failure
        return paths['stdout'].read_text(errors='replace')

    @staticmethod
    def devices(data):
        require(isinstance(data.get('devices'), dict), 'Invalid device inventory')
        return [(runtime, d) for runtime, group in data['devices'].items() for d in group]

    def recover(self, inventory):
        require(not self.recovered and not self.active and not self.unknown_spawn, 'Recovery not safe')
        self.recovered = True
        matches = [d for runtime, d in self.devices(inventory) if runtime == self.intent['runtime']
                   and d.get('name') == self.intent['name'] and d.get('deviceTypeIdentifier') == self.intent['type']
                   and d.get('udid', '').upper() not in self.baseline]
        require(len(matches) == 1, 'Create ownership not uniquely established')
        self.owned = str(uuid.UUID(matches[0]['udid'])).upper()
        self.report['owned_uuid'] = self.owned
        self.save()

