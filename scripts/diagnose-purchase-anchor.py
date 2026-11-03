#!/usr/bin/env python3
"""Capture one same-build, fresh-Simulator purchase-anchor pair; never release acceptance."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import sys
import time
import uuid

WORK_SECONDS, CLEANUP_SECONDS = 1800, 180
BUILD_CAP, TEST_CAP, CASE_SECONDS = 420, 780, 180  # Command caps include eight-second stop reserve.
CASE = 'BatchImportUITests/testDiagnosticPurchasePresentationAnchor()'
SELECTOR = 'TripfolioUITests/' + CASE.removesuffix('()')
MODES = ('child', 'ownedAncestor')
RUNTIME = 'com.apple.CoreSimulator.SimRuntime.iOS-26-2'
DEVICE = 'com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro'
PINS = {
    'qualify-release.py': 'f4c078d8f2c3910f2930a30ba7f48944bbe66a9c8b778bea9790c1c50bf9d803',
    'recovery_core.py': '97b24cd6254af03a6081e92f7f06f9e994ba65e809d8198418687b0ec25ab790',
    'recovery_process.py': '5e9d2b1d7d1702bade1cd44abdf2b5ebbe143e8f72a86014f8a6575265792bcc',
    'batch_checkpoint.py': 'aa66e1bfedb89d7becb7985bee735cafbaec447bea2061cb392880a2be17f185',
}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def context(env, machine):
    profiles = {
        'macos-15': {'name':'default','runner':'macos-15','runner_architecture':'ARM64','architecture':'arm64'},
        'macos-15-intel': {'name':'intel-batch','runner':'macos-15-intel','runner_architecture':'X64','architecture':'x86_64'},
    }
    profile = profiles.get(env.get('PURCHASE_ANCHOR_RUNNER'))
    require(env.get('GITHUB_ACTIONS') == 'true' and env.get('RUNNER_OS') == 'macOS'
            and profile is not None and env.get('RUNNER_ARCH') == profile['runner_architecture']
            and machine == profile['architecture'], 'Hosted diagnostic runner identity mismatch')
    require(env.get('GITHUB_REPOSITORY') == '4alvit/travel-documents-ios'
            and env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
            and env.get('GITHUB_WORKFLOW') == 'Purchase anchor diagnostic'
            and env.get('GITHUB_JOB') == 'anchor', 'Unexpected diagnostic workflow context')
    require(env.get('GITHUB_REF') == 'refs/heads/diagnostic/purchase-anchor', 'Diagnostic branch required')
    require(re.fullmatch('[0-9a-f]{40}', env.get('GITHUB_SHA', '')), 'Missing source commit')
    for key in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'):
        require(re.fullmatch('[1-9][0-9]*', env.get(key, '')), 'Invalid run identity')
    require(env.get('DEVELOPER_DIR') == '/Applications/Xcode_26.2.app/Contents/Developer', 'Wrong developer path')
    job = {key:env[key] for key in ('GITHUB_REPOSITORY','GITHUB_SHA','GITHUB_REF',
            'GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_EVENT_NAME','GITHUB_WORKFLOW')}
    job['runner_profile'] = profile
    return job


def load_helpers(root):
    for name, expected in PINS.items():
        path = root / 'scripts' / name
        require(path.is_file() and not path.is_symlink()
                and hashlib.sha256(path.read_bytes()).hexdigest() == expected, 'Helper changed: ' + name)
    spec = importlib.util.spec_from_file_location('purchase_anchor_qualification', root/'scripts/qualify-release.py')
    q = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(q)
    return q, q.recovery


def argv_for(root, derived, settings, operation, owned=None, result=None):
    require(operation in ('build-for-testing', 'test-without-building'), 'Unknown native operation')
    require((operation == 'build-for-testing') == (owned is None and result is None), 'Invalid native destination')
    destination = 'generic/platform=iOS Simulator' if owned is None else 'platform=iOS Simulator,id=' + str(uuid.UUID(owned)).upper()
    argv = ['xcodebuild','-project',str(root/'Tripfolio.xcodeproj'),'-scheme','Tripfolio','-configuration','Debug',
            '-destination',destination,'-destination-timeout','30','-derivedDataPath',str(derived),
            '-parallel-testing-enabled','NO','-maximum-concurrent-test-simulator-destinations','1',
            '-default-test-execution-time-allowance',str(CASE_SECONDS),
            '-maximum-test-execution-time-allowance',str(CASE_SECONDS),'-only-testing:'+SELECTOR,
            'CODE_SIGNING_ALLOWED=NO',*settings]
    if result is not None:
        argv += ['-resultBundlePath',str(result)]
    return argv + [operation]


def validate_result(q, summary, tree, owned, selection):
    pending = [(node,0) for node in tree.get('testNodes', [])]
    seen = 0
    while pending:
        node,depth = pending.pop(); seen += 1
        require(isinstance(node,dict) and seen <= 10000 and depth <= 100, 'Result tree bounds exceeded')
        require(node.get('nodeType') != 'Runtime Warning', 'Runtime warning in test tree')
        children = node.get('children',[])
        require(isinstance(children,list), 'Invalid result children')
        pending.extend((child,depth+1) for child in children)
    q.recovery.validate_result(summary,tree,CASE,owned)
    q.validate_runtime_result('batch',selection,summary)
    require(summary.get('testFailures') == [] and summary.get('runtimeWarnings',[]) == [], 'Native failures or warnings')


def validate_index_store_disabled(raw):
    values = json.loads(raw)
    require(isinstance(values,list) and len(values)<=16,'Invalid diagnostic build settings')
    result = {}
    for target in ('Tripfolio','TripfolioTests','TripfolioUITests'):
        matches = [value for value in values if isinstance(value,dict) and value.get('target')==target]
        require(len(matches)==1,'Missing or ambiguous diagnostic target: '+target)
        settings = matches[0].get('buildSettings')
        require(isinstance(settings,dict) and settings.get('COMPILER_INDEX_STORE_ENABLE')=='NO',
                'Compiler index store must be disabled: '+target)
        result[target] = settings['COMPILER_INDEX_STORE_ENABLE']
    return result


def make_runner(q, core):
    class Context(core.Recovery):
        """Use reviewed process/resource primitives with one externally allocated clock."""
        accept_nonzero_exit = core.base.Smoke.accept_nonzero_exit

        def __init__(self, pair, out, final, name):
            self.pair, self.out, self.candidate = pair, out, pair.root
            self.ops = core.base.RealOps(dict(os.environ), str(pair.root))
            self.plan = {'runtime':RUNTIME,'device_type':DEVICE}
            self.host = {'machine':pair.profile['architecture']}
            self.t0, self.final = pair.started, final
            self.limit, self.write_deadline, self.phase = pair.work_end, pair.final, 'work'
            self.active, self.absent_groups = {}, set()
            self.log_total, self.interrupted, self.cleaning = 0, False, False
            self.unknown_spawn = self.create_attempted = self.recovered = False
            self.owned, self.baseline, self.root_id = None, set(), None
            self.originals, self.next_scan = {}, self.t0
            self.intent = {'name':name,'runtime':RUNTIME,'type':DEVICE}
            self.report = {'status':'running','commands':[],'errors':[],'attempts':{},'resources':[],
                           'cleanup_verified':False,'release_acceptance':False}
            self.out.mkdir(mode=0o700)
            self.output_id = core.identity_of(self.out)
            if not hasattr(pair, 'output_id'): pair.output_id = core.identity_of(pair.out)
            self.save()

        def monitor(self, *, command_owner=None):
            require(command_owner is None, 'No delegated process scanner in this diagnostic')
            started=self.ops.now()
            pending=self.report['commands'][-1] if self.report['commands'] else None
            unfinished=pending is not None and 'finish' not in pending
            child=self.active.get(pending.get('pgid')) if unfinished else None
            args=pending.get('argv',[]) if unfinished else []
            writer=(child is not None and child.pid==pending.get('pgid') and args[:1]==['xcodebuild']
                    and pending['id'] in ('build-for-testing','selected-tests')
                    and args[-1:] in (['build-for-testing'],['test-without-building']))
            boot=(unfinished and self.owned is not None and pending['id']=='boot-ready'
                  and args==['/usr/bin/xcrun','simctl','bootstatus',self.owned,'-b']
                  and ((child is not None and child.pid==pending.get('pgid'))
                       or ('pgid' not in pending and not self.active and not self.unknown_spawn)))
            coordinator=getattr(self.pair,'commands',None)
            postbuild_boot=(boot and self.pair.report.get('shared_build_verified') is True
                and self.pair.current is self and not self.unknown_spawn
                and len(self.active)==(1 if child is not None else 0)
                and coordinator is not None and not coordinator.active and not coordinator.unknown_spawn)
            boundary=getattr(self,'_boot_boundary',None)
            post=bool(boundary and boundary.get('post'))
            if boundary and boundary.get('record') is not None:
                require(pending is boundary['record'],'Boot accounting record changed')
                settled=(self.boot_boundary_eligible(pending['id'],pending['argv'])
                         and pending.get('returncode')==0 and 'error' not in pending
                         and pending.get('stop',{}).get('group_absent') is True
                         and pending.get('stop',{}).get('leader_reaped') is True)
                if post:
                    require(settled and 'finish' in pending,'Boot postcheck ownership incomplete')
                else:
                    # Base command checkpoints after stop/close but before setting
                    # finish. Only its proven successful closure may bridge that gap.
                    require(postbuild_boot or settled,'Boot accounting ownership or build proof changed')
            if boundary and boundary.get('record') is not None and boundary['record'] is pending and not post:
                # Deliberate phase policy: unexpected subtree writes/peak size are
                # checked at full boundaries, not recursively on every boot pump.
                deadline=min(self.limit,self.t0+pending['work_deadline'])
                self.timecheck();require(self.ops.now()<deadline,'Boot phase deadline exceeded')
                require(core.identity_of(self.pair.out)==self.pair.output_id,'Boot output root changed')
                free=shutil.disk_usage(self.pair.out).free
                require(free>=core.CAPS['work_free_bytes'],'Work free-space floor reached')
                require(self.log_total<=core.base.ALL_LOG
                        and set(pending['bytes'])=={'stdout','stderr'}
                        and all(0<=n<=core.base.PER_LOG for n in pending['bytes'].values()),'Boot log cap exceeded')
                require(core.identity_of(self.pair.out)==self.pair.output_id,'Boot output root changed')
                self.timecheck();require(self.ops.now()<deadline,'Boot phase deadline exceeded')
                proof=pending['boot_accounting']
                proof['interim_checks']+=1
                proof['last_interim']={'elapsed':self.ops.now()-self.t0,'free_bytes':free,
                                       'scope':'root_free_log_ownership_deadlines_no_recursive_scan'}
                self.next_scan=self.ops.now()+core.CAPS['scan_interval_seconds']
                return
            allowance=(core.CAPS['phase_scan_seconds'] if writer or postbuild_boot else core.CAPS['boot_scan_seconds']
                       if boot else core.CAPS['scan_seconds'])
            if post: allowance=core.CAPS['phase_scan_seconds']
            deadline=min(self.limit,started+allowance)
            if unfinished or post: deadline=min(deadline,self.t0+pending['work_deadline'])
            observation={}
            def check():
                self.timecheck()
                require(self.ops.now()<deadline,'Shared output scan deadline exceeded')
            try:
                check()
                require(shutil.disk_usage(self.pair.out).free>=core.CAPS['work_free_bytes'],'Work free-space floor reached')
                row=core.live_sizes(self.pair.out,self.pair.output_id,self.ops.now,deadline,self.timecheck,
                    observation=observation,allow_xcresult_restart=writer,allow_products_restart=writer)
                check()
                free=shutil.disk_usage(self.pair.out).free
                check();require(free>=core.CAPS['work_free_bytes'],'Work free-space floor reached')
            except BaseException as error:
                self.report.setdefault('resource_scan_failure',{'started_elapsed':started-self.t0,
                    'deadline_elapsed':deadline-self.t0,'observation':observation,'error':repr(error)[:512]})
                raise
            row.update(elapsed=self.ops.now()-self.t0,free_bytes=free,scope='whole_shared_pair_output',
                       deadline_elapsed=deadline-self.t0,requested_scan_seconds=allowance)
            self.report['resources'].append(row)
            self.next_scan=self.ops.now()+core.CAPS['scan_interval_seconds']
            if boundary and postbuild_boot and boundary.get('record') is None:
                require('pgid' not in pending and not self.active,'Boot full precheck must precede spawn')
                boundary['record']=pending
                pending['boot_accounting']={'policy':'full_pre_and_post; interim root/free/log/ownership/deadline checks; transient subtree size/writes unobserved; boundary violations checked at postcheck',
                    'full_pre_verified':True,'full_post_verified':False,'interim_checks':0,
                    'pre_elapsed':row['elapsed'],'post_status':'not_completed'}
            elif post:
                pending['boot_accounting'].update(full_post_verified=True,post_status='verified',post_elapsed=row['elapsed'])

        def pump(self,p,record,handles):
            self.log_total=getattr(self.pair,'log_total',0)
            try: return super().pump(p,record,handles)
            finally: self.pair.log_total=self.log_total

        def boot_boundary_eligible(self,label,argv):
            coordinator=getattr(self.pair,'commands',None)
            return (not self.cleaning and label=='boot-ready' and self.owned is not None
                and argv==['/usr/bin/xcrun','simctl','bootstatus',self.owned,'-b']
                and self.pair.current is self and self.pair.report.get('shared_build_verified') is True
                and not self.active and not self.unknown_spawn and coordinator is not None
                and not coordinator.active and not coordinator.unknown_spawn)

        def command(self, label, argv, cap=38):
            argv=[str(x) for x in argv]
            if not self.boot_boundary_eligible(label,argv):
                return super().command(label,argv,cap)
            require(getattr(self,'_boot_boundary',None) is None,'Nested boot accounting')
            boundary={'record':None,'post':False};self._boot_boundary=boundary
            try:
                result=super().command(label,argv,cap)
                require(boundary['record'] is not None,'Boot full precheck missing')
                boundary['post']=True
                self.monitor()
                self.save()
                return result
            except BaseException as error:
                if boundary['record'] is not None:
                    boundary['record']['boot_accounting'].update(post_status='failed' if boundary['post'] else 'not_completed',
                        boundary_error=repr(error)[:512])
                raise
            finally:
                self._boot_boundary=None

        def stop(self,p,deadline,record):
            now=self.ops.now()
            coordinator=getattr(self.pair,'commands',None)
            if (self.cleaning and now>=deadline and self.owned is not None
                and self.pair.current is self
                and record.get('id') in ('shutdown','delete')
                and record.get('argv')==['/usr/bin/xcrun','simctl',record['id'],self.owned]
                and self.report['commands'] and record is self.report['commands'][-1]
                and record.get('pgid')==p.pid and self.active.get(p.pid) is p and len(self.active)==1
                and p.returncode is None and not self.unknown_spawn
                and 'stop' not in record
                and coordinator is not None and not coordinator.active and not coordinator.unknown_spawn):
                end=min(self.limit,self.write_deadline-core.CAPS['receipt_seconds'],
                        self.pair.final-core.CAPS['receipt_seconds'],now+8)
                if now<end:
                    record['late_first_stop']={'original_deadline':deadline-self.t0,
                        'admitted_elapsed':now-self.t0,'deadline':end-self.t0,
                        'policy':'first owned cleanup stop only; original command timeout and overrun remain failures'}
                    deadline=end
            return super().stop(p,deadline,record)

        def checkpoint(self, **kwargs):
            coordinator = getattr(self.pair, 'commands', None)
            other = self.pair.current if self is coordinator else coordinator
            require(other is None or (not other.active and not other.unknown_spawn),
                    'Other diagnostic process ownership unresolved')
            return super().checkpoint(**kwargs)

        def check(self):
            self.checkpoint()

        def source(self):
            return self.pair.source('source-before-' + self.out.name)

        def prepare_files_ui_baseline(self):
            # Deliberate diagnostic-only setup: no Files queries, fixture, or prerequisite.
            pass

        def sim(self,label,*args,cap=38):
            return self.command(label,['/usr/bin/xcrun','simctl',*args],188 if label=='boot-ready' else cap)

    class Pair:
        def __init__(self, root, job):
            self.root, self.job = root, job
            self.profile = dict(job['runner_profile'])
            self.started = time.monotonic()
            self.work_end, self.final = self.started+WORK_SECONDS, self.started+WORK_SECONDS+CLEANUP_SECONDS
            self.out = root/'build'/('PurchaseAnchor-'+job['GITHUB_RUN_ID']+'-'+job['GITHUB_RUN_ATTEMPT'])
            require(self.out.parent.is_dir() and not self.out.parent.is_symlink(), 'Unsafe build parent')
            self.current = None
            self.report = {'status':'running','source':{'commit':job['GITHUB_SHA']},'job':job,
                           'diagnostic':'same-build-purchase-anchor-pair','release_acceptance':False,
                           'runner_profile':self.profile,
                           'limits':{'work_seconds':WORK_SECONDS,'cleanup_seconds':CLEANUP_SECONDS,
                           'build_total_cap':BUILD_CAP,'test_total_cap':TEST_CAP,'stop_reserve':8,'case_seconds':CASE_SECONDS},
                           'arm_order':list(MODES),'arms':{},'errors':[]}
            self.commands = Context(self,self.out,self.final,'not-a-device')
            self.commands.job = job
            self.commands.root = root
            self.commands.report['pair'] = self.report
            self.derived = self.out/'DerivedData'
            require(not os.path.lexists(self.derived), 'Derived output preexists')
            self.before = None; self.products = None; self.product_paths = None
            self.baseline = None; self.used_devices = set()
            self.commands.save()

        def interrupted(self):
            return self.commands.interrupted or (self.current is not None and self.current.interrupted)

        def signal(self,*_):
            self.commands.interrupted = True
            if self.current is not None:
                self.current.signal()

        def source(self,label):
            actual = q.Qualification.source(self.commands,label)
            if self.before is None:
                self.before = actual
                self.report['source']['tree'] = actual['tree']
            require(actual == self.before,'Tracked source changed during diagnostic')
            return actual

        def product_snapshot(self,label):
            require(self.product_paths is not None,'No bound shared products')
            value = {name:q.compiled_identity(path,self.commands.checkpoint) for name,path in self.product_paths.items()}
            if self.products is None: self.products = value
            require(value == self.products,'Shared build content or modes changed')
            self.commands.persist(label+'.json',value)
            return value

        def admit_build(self):
            self.commands.checkpoint()
            free=shutil.disk_usage(self.out).free
            self.commands.checkpoint()
            require(free>=core.CAPS['admission_free_bytes'],'Insufficient space before shared build')
            self.report['build_admission']={'free_bytes':free,'elapsed':time.monotonic()-self.started}

        def prepare(self):
            self.source('source-before')
            c = self.commands
            values = {}
            for name,args in [('xcode',['xcodebuild','-version']),('developer',['xcode-select','-p']),
                              ('sdk',['xcrun','--sdk','iphonesimulator','--show-sdk-version']),('architecture',['uname','-m'])]:
                values[name] = c.command(name,args).strip()
            require(values == {'xcode':q.XCODE_VERSION,'developer':q.DEVELOPER_DIR,'sdk':'26.2','architecture':self.profile['architecture']},
                    'Unexpected actual toolchain')
            self.report['toolchain'] = values
            raw = json.loads(c.sim('runtimes','list','runtimes','--json',cap=158))
            matches = [x for x in raw.get('runtimes',[]) if x.get('identifier')==RUNTIME]
            require(len(matches)==1 and matches[0].get('version')=='26.2' and matches[0].get('buildversion')=='23C54'
                    and matches[0].get('isAvailable') is True and self.profile['architecture'] in matches[0].get('supportedArchitectures',[])
                    and sum(x.get('identifier')==DEVICE for x in matches[0].get('supportedDeviceTypes',[]))==1,
                    'Wrong actual runtime/device')
            self.selection = {'identifier':RUNTIME,'version':'26.2','build':'23C54','architecture':self.profile['architecture'],'sdk_version':'26.2','sdk_matched':True}
            self.report['runtime_selection'] = self.selection
            selection = q.focused_build_selection('batch',self.profile,self.before['files'])
            self.settings = [*selection['build_settings'],'COMPILER_INDEX_STORE_ENABLE=NO']
            self.report['focused_build'] = selection
            self.report['diagnostic_build_settings'] = list(self.settings)
            c.command('generate-project',['xcodegen','generate'],128)
            self.admit_build()
            c.once('build-for-testing')
            c.command('build-for-testing',argv_for(self.root,self.derived,self.settings,'build-for-testing'),BUILD_CAP)
            settings_argv = ['xcodebuild','-project',self.root/'Tripfolio.xcodeproj','-scheme','Tripfolio','-configuration','Debug',
                '-destination','generic/platform=iOS Simulator','-derivedDataPath',self.derived,
                'CODE_SIGNING_ALLOWED=NO',*self.settings,'-showBuildSettings','-json','build-for-testing']
            raw = c.command('build-settings',settings_argv,48)
            self.report['compiler_index_store'] = validate_index_store_disabled(raw)
            self.product_paths = q.shared_product_paths(raw,self.derived,tuple(self.settings))
            self.product_snapshot('products-built')
            self.source('source-after-build')
            self.report['shared_build_verified']=True

        def capture(self, arm, mode):
            result = self.out/(mode+'.xcresult')
            evidence = arm.report.setdefault('native_result',{'status':'not_produced','case':CASE,
                'inspection_copy_closed':True,'evidence_capture_complete':False,
                'storekit_entry':'unclassified_pending_independent_app_log_and_transaction_review',
                'stage_limit':'Selection marker precedes another precondition check; XCTest failure alone does not establish StoreKit entry.'})
            if not os.path.lexists(result):
                evidence['evidence_capture_complete']=True
                return
            require(result.is_dir() and not result.is_symlink(),'Unexpected result path type')
            require(not arm.active and not arm.unknown_spawn,'Result writer ownership unresolved')
            manifest = core.tree_manifest(result,arm.checkpoint)
            evidence['manifest'] = arm.persist('original-manifest.json',manifest)
            if manifest.get('Info.plist',{}).get('kind')!='file' or manifest.get('Data',{}).get('kind')!='directory':
                evidence['status']='partial_result'
                evidence['evidence_capture_complete']=True
                return
            # Read only a verified owned copy; preserve the original for independent analysis.
            copy = self.out/(mode+'-inspection.xcresult')
            evidence['inspection_copy_closed']=False
            arm.copy_tree(result,copy,manifest)
            copy_id=core.identity_of(copy)
            try:
                for kind in ('attachments','diagnostics'):
                    destination=arm.out/kind
                    require(not os.path.lexists(destination),'Export destination preexists')
                    arm.command('export-'+kind,['xcrun','xcresulttool','export',kind,
                                '--path',copy,'--output-path',destination],68)
                    evidence[kind]=arm.persist(kind+'-manifest.json',core.tree_manifest(destination,arm.checkpoint))
                parsed={}
                for kind in ('summary','tests'):
                    raw=arm.command('result-'+kind,['xcrun','xcresulttool','get','test-results',kind,'--path',copy,'--compact'],68)
                    parsed[kind]=json.loads(raw); arm.persist(kind+'.json',parsed[kind])
                evidence.update(status='read',runtimeWarnings=parsed['summary'].get('runtimeWarnings','not_reported'),
                                runtimeWarnings_reported='runtimeWarnings' in parsed['summary'])
                try:
                    validate_result(q,parsed['summary'],parsed['tests'],arm.owned,self.selection)
                    evidence['selected_case_passed']=True
                except Exception as error:
                    evidence['selected_case_passed']=False; evidence['validation_error']=repr(error)
            finally:
                require(core.tree_manifest(result,arm.checkpoint)==manifest,'Original xcresult changed during reading')
                evidence['original_bytes_modes_unchanged']=True
                if not arm.active and not arm.unknown_spawn:
                    copied=core.tree_manifest(copy,arm.checkpoint)
                    require(all(copied.get(name)==item for name,item in manifest.items()),'Original entry changed in inspection copy')
                    extras=set(copied)-set(manifest)
                    require(extras<={'database.sqlite3'},'Unexpected inspection sidecar')
                    if extras:
                        item=copied['database.sqlite3']
                        require(item['kind']=='file' and item['mode'] in (0o600,0o644)
                                and 0<=item['bytes']<=16*1024*1024,'Invalid inspection database sidecar')
                    evidence['inspection_manifest']=arm.persist('inspection-after-manifest.json',copied)
                    require(core.identity_of(copy)==copy_id,'Inspection directory identity changed')
                    shutil.rmtree(copy)
                    evidence['inspection_copy_removed']=True
                    evidence['inspection_copy_closed']=True
            evidence['evidence_capture_complete']=True

        def install_aut(self,arm):
            # SKTestSession preflight runs before app.launch in the UI case.
            # Register the same bound AUT on both fresh devices before that case.
            require(self.current is arm and arm.owned is not None,
                    'AUT installation requires the current owned device')
            arm.checkpoint()
            arm.once('install-aut')
            arm.sim('install-aut','install',arm.owned,self.product_paths['Tripfolio'],cap=38)
            raw=arm.sim('pretest-installed-Tripfolio','get_app_container',arm.owned,q.APP_ID,'app',cap=38)
            path=arm.owned_path(raw,('data','Containers','Bundle','Application'),self.product_paths['Tripfolio'].name)
            identity=q.compiled_identity(path,arm.checkpoint)
            require(identity['content']==self.products['Tripfolio']['content'],
                    'Pretest installed AUT bytes differ from shared build')
            arm.persist('pretest-installed-aut.json',{'identity':identity,'content_matches_shared':True,
                'modes_match_shared':identity['modes']==self.products['Tripfolio']['modes']})
            arm.report['pretest_installed_aut_verified']=True

        def installed(self,arm):
            installed={}
            for name,identifier in [('Tripfolio',q.APP_ID),('TripfolioUITestsRunner',q.RUNNER_ID)]:
                raw=arm.sim('installed-'+name,'get_app_container',arm.owned,identifier,'app',cap=38)
                path=arm.owned_path(raw,('data','Containers','Bundle','Application'),self.product_paths[name].name)
                identity=q.compiled_identity(path,arm.checkpoint)
                require(identity['content']==self.products[name]['content'],'Installed product bytes differ from shared build')
                installed[name]={'identity':identity,'content_matches_shared':True,
                                 'modes_match_shared':identity['modes']==self.products[name]['modes']}
            arm.persist('installed-products.json',installed)
            arm.report['installed_product_content_verified']=True

        def run_arm(self,mode,index):
            self.commands.checkpoint()
            self.source('source-enter-'+mode); self.product_snapshot('products-before-'+mode)
            arm=Context(self,self.out/mode,self.final,'TripDocket-Anchor-'+mode+'-'+str(uuid.uuid4()))
            self.current=arm; self.report['arms'][mode]=arm.report
            arm.report['mode']=mode; arm.report['runtime_selection']=self.selection
            arm.report['environment_overrides']={'TEST_RUNNER_TRIPDOCKET_PURCHASE_ANCHOR_CONTROL':'1',
                'TEST_RUNNER_TRIPDOCKET_PURCHASE_ANCHOR_MODE':mode,'TEST_RUNNER_NSUnbufferedIO':'YES','NSUnbufferedIO':'YES'}
            post_verified=False; normal_cleanup=False
            try:
                arm.setup()
                if self.baseline is None: self.baseline = arm.report['baseline']
                require(arm.report['baseline'] == self.baseline, 'Pair baseline inventory changed')
                require(arm.owned not in self.used_devices, 'Pair reused a Simulator')
                self.used_devices.add(arm.owned)
                self.install_aut(arm)
                require(arm.report.get('pretest_installed_aut_verified') is True, 'Pretest AUT proof missing')
                arm.once('selected-tests')
                arm.ops.env={**arm.ops.env,**arm.report['environment_overrides']}
                try:
                    arm.command('selected-tests',argv_for(self.root,self.derived,self.settings,'test-without-building',
                                arm.owned,self.out/(mode+'.xcresult')),TEST_CAP)
                    arm.report['native_command_passed']=True
                except Exception as error:
                    arm.report['native_command_passed']=False; arm.error('Native command: '+repr(error))
                require(not arm.active and not arm.unknown_spawn,'Native ownership unresolved')
                require(not self.interrupted(),'Diagnostic interrupted')
                for name,operation in [('Result',lambda:self.capture(arm,mode)),('Installed products',lambda:self.installed(arm))]:
                    try: operation()
                    except Exception as error: arm.error(name+': '+repr(error))
                self.source('source-after-'+mode); self.product_snapshot('products-after-'+mode)
                captured=arm.report.get('native_result',{})
                post_verified=(arm.report.get('installed_product_content_verified') is True
                               and captured.get('evidence_capture_complete') is True
                               and captured.get('inspection_copy_closed') is True)
            except BaseException as error:
                arm.error('Arm: '+repr(error))
            finally:
                # Only ordinary first-arm cleanup may precede another arm, wholly within WORK.
                normal_cleanup=(index==0 and post_verified and not self.interrupted()
                                and not arm.active and not arm.unknown_spawn
                                and time.monotonic()+core.CAPS['cleanup_seconds']<self.work_end)
                arm.final=self.work_end if normal_cleanup else self.final
                try: arm.cleanup()
                except BaseException as error: arm.error('Cleanup: '+repr(error))
                arm.report['status']=('passed_pending_independent_review' if arm.report.get('native_command_passed')
                    and arm.report.get('native_result',{}).get('selected_case_passed') and not arm.report['errors']
                    and arm.report['cleanup_verified'] else 'failed')
                arm.report['unresolved_groups']=sorted(arm.active);arm.report['unknown_spawn']=arm.unknown_spawn
                arm.save(); self.commands.save()
            safe=(arm.report['cleanup_verified'] and not arm.active and not arm.unknown_spawn
                  and post_verified and not self.interrupted())
            self.current=None
            require(safe,'Arm did not close source/product/process/device ownership')
            if index==0:
                require(normal_cleanup,'No work budget for second arm after first cleanup')
            return arm.report['status']

        def run(self):
            try:
                self.prepare()
                for index,mode in enumerate(MODES): self.run_arm(mode,index)
            except BaseException as error:
                self.report['errors'].append(repr(error))
            finally:
                if self.interrupted(): self.report['errors'].append('Interrupted')
                # Finalize only recorded ownership facts; never retry stop or probe an unknown group.
                coordinator=self.commands.report
                coordinator['unresolved_groups']=sorted(self.commands.active)
                coordinator['unknown_spawn']=self.commands.unknown_spawn
                coordinator['cleanup_verified']=(not self.commands.active and not self.commands.unknown_spawn
                    and not self.commands.create_attempted and self.commands.owned is None
                    and all(row.get('stop',{}).get('group_absent') is True
                            and row.get('stop',{}).get('leader_reaped') is True
                            for row in coordinator['commands'] if row.get('pgid') is not None))
                self.report['cleanup_verified']=(coordinator['cleanup_verified']
                    and all(row.get('cleanup_verified') is True and not row.get('unresolved_groups')
                            and row.get('unknown_spawn') is False for row in self.report['arms'].values()))
                complete=(list(self.report['arms'])==list(MODES) and not self.report['errors']
                    and self.report['cleanup_verified']
                    and all(x['status']=='passed_pending_independent_review' for x in self.report['arms'].values()))
                self.report['status']='diagnostic_pair_captured_pending_review' if complete else 'failed'
                self.report['elapsed_seconds']=time.monotonic()-self.started
                self.commands.save()
            return 0 if complete else 1
    return Pair


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true',help='Run only in the explicitly pinned manual diagnostic workflow')
    args=parser.parse_args(argv)
    require(args.run,'Explicit --run required')
    job=context(os.environ,os.uname().machine)
    root=Path(__file__).resolve().parents[1]
    build=root/'build'
    require(not build.is_symlink(),'Unsafe build directory')
    build.mkdir(exist_ok=True)
    q,core=load_helpers(root)
    runner=make_runner(q,core)(root,job)
    old={sig:signal.signal(sig,runner.signal) for sig in (signal.SIGINT,signal.SIGTERM)}
    try: return runner.run()
    finally:
        for sig,handler in old.items(): signal.signal(sig,handler)


if __name__=='__main__':
    sys.exit(main())
