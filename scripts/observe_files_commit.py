#!/usr/bin/env python3
"""Opt-in diagnostic entrypoint. Existing Recovery remains the acceptance owner."""
import hashlib
import importlib.util
from pathlib import Path
import sys
import json
import os
import stat
import re

HERE=Path(__file__).resolve().parent
HOSTED_SHA='4e96eafb138f408df5b2de450c5015b94192672b6103e7ba8f1632f916e7b7c5'
# Exact reviewed hosted adapter digest, including the source-context hook.
if hashlib.sha256((HERE/'recovery_hosted.py').read_bytes()).hexdigest()!=HOSTED_SHA:
    raise RuntimeError('Canonical hosted adapter changed')
spec=importlib.util.spec_from_file_location('observed_hosted',HERE/'recovery_hosted.py')
hosted=importlib.util.module_from_spec(spec);spec.loader.exec_module(hosted)


DIAGNOSTIC_REF='refs/heads/diagnostic/files-commit-observation-20261030'
BASE_COMMIT='f20ac06a54e5e862def0fd6b3205982508f652a1'


def expected_commit_message(tree):
    return ('Observe the Files inline commit boundary\n\n'
            'TripDocket-Observation: files-inline-commit-v2\n'
            'TripDocket-Reviewed-Base: '+BASE_COMMIT+'\n'
            'TripDocket-Reviewed-Tree: '+tree+'\n')


def validate_push_identity(job,event):
    # Preserve the actual GitHub event. No synthetic dispatch inputs or env.
    hosted.require(isinstance(event,dict) and isinstance(event.get('head_commit'),dict)
                   and isinstance(event.get('repository'),dict), 'Missing push event objects')
    hosted.require(re.fullmatch(r'[0-9a-f]{40}',job.get('GITHUB_SHA','')) is not None, 'Invalid push SHA')
    hosted.require(job.get('GITHUB_EVENT_NAME')=='push'
                   and job.get('GITHUB_REF')==DIAGNOSTIC_REF
                   and job.get('GITHUB_RUN_ATTEMPT')=='1', 'Not the one diagnostic push')
    hosted.require(job.get('GITHUB_REPOSITORY')=='4alvit/travel-documents-ios'
                   and event.get('repository',{}).get('full_name')==job['GITHUB_REPOSITORY'],
                   'Diagnostic repository mismatch')
    hosted.require(event.get('ref')==DIAGNOSTIC_REF and event.get('created') is True
                   and event.get('deleted') is False and event.get('forced') is False
                   and event.get('before')=='0'*40, 'Diagnostic branch must be newly created once')
    hosted.require(event.get('after')==job.get('GITHUB_SHA')
                   and event.get('head_commit',{}).get('id')==job.get('GITHUB_SHA'),
                   'Diagnostic event head mismatch')


def diagnostic_source_context(job,event,commit,raw_commit):
    validate_push_identity(job,event)
    actual=hosted.parse_commit(raw_commit,job['GITHUB_SHA'])
    hosted.require(actual==commit and commit['parents']==[BASE_COMMIT],
                   'Diagnostic commit must have the one exact reviewed parent')
    hosted.require(commit['signature_present'], 'Diagnostic commit must carry a signature')
    message=raw_commit.partition('\n\n')[2]
    hosted.require(message==expected_commit_message(commit['tree']), 'Reviewed tree trailer differs from actual tree')
    hosted.require(event['head_commit'].get('message','').rstrip('\n')==message.rstrip('\n'),
                   'Push message differs from signed commit message')
    # Trust anchor: root independently checks this tree against the frozen
    # reviewed manifest AND verifies the signed commit before the single push.
    # A trailer alone is not a human review or local cryptographic verification.
    return {'kind':'push','checkout':commit,'diagnostic_ref':DIAGNOSTIC_REF,
            'diagnostic_source_binding':{'base_commit':BASE_COMMIT,'reviewed_tree':commit['tree'],
              'signed_message_matches_actual_tree':True,'exact_first_push_event':True,
              'root_review_and_signature_verification_required_before_push':True,
              'signature_cryptographically_verified_here':False}}


class ObservedRecovery(hosted.HostedRecovery):
    def capture_source(self):
        validate_push_identity(self.job,self.event)
        super().capture_source()

    def source_context(self,commit,raw_commit):
        return diagnostic_source_context(self.job,self.event,commit,raw_commit)

    def discover_profile(self):
        super().discover_profile()
        # Observation equivalence gate only. Never switch/download Xcode or a
        # runtime to satisfy it; stop before creating a device when unavailable.
        hosted.require(self.host['xcode_version']=='Xcode 16.4\nBuild version 16F6'
                       and self.host['sdk_version']=='18.5', 'Observation profile differs from retained failure')

    def phase_argv(self,phase):
        original=super().phase_argv(phase)
        if phase!='prepare':return original
        return [sys.executable,'-B',str(self.candidate/'scripts/files_commit_observer.py'),
                '--owned-uuid',self.owned,'--run-token',self.folder_name[-36:],'--output',str(self.out/'CommitObservation'),'--',*original]

    def run(self):
        code=super().run()
        try:
            self.timecheck()
            rows=[r for r in self.report['commands'] if r['id']=='phase-prepare']
            hosted.require(len(rows)==1 and not self.active and not self.unknown_spawn,
                           'Unresolved observation group')
            stop=rows[0].get('stop',{})
            hosted.require(stop.get('group_absent') is True and stop.get('leader_reaped') is True,
                           'Observation group closure unconfirmed')
            folder=self.out/'CommitObservation'
            hosted.core.identity_of(folder)
            observation=json.loads(read_pinned(folder/'receipt.json',128*1024,self.timecheck)[0])
            hosted.require(observation.get('owned_uuid')==self.owned
                           and observation.get('run_token')==self.folder_name[-36:], 'Observation identity mismatch')
            public=self.out/'CommitObservationPublic'
            hosted.require(not os.path.lexists(public), 'Publication already exists')
            staging=self.out/'CommitObservationStaging';staging.mkdir(mode=0o700)
            observation['outer_group_absence_verified']=True
            video=observation.get('video',{})
            if video.get('status')=='structurally_finalized_pending_playback_review':
                path=folder/'boundary.mp4'
                raw,pin=read_pinned(path,64*hosted.core.MIB,self.timecheck)
                hosted.require(len(raw)==video['bytes'] and hashlib.sha256(raw).hexdigest()==video['sha256'],
                               'Video differs from finalized structure check')
                del raw
                self.timecheck()
                hosted.require(file_pin(path.lstat())==pin,'Video changed before publication')
                path.rename(staging/'boundary.mp4')
                hosted.require(file_pin((staging/'boundary.mp4').lstat())==pin,'Video changed at publication')
                video['published']=True
            raw=hosted.core.encoded(observation)
            hosted.require(len(raw)<=128*1024,'Public observation receipt cap')
            self.timecheck()
            with (staging/'receipt.json').open('xb') as stream:stream.write(raw)
            hosted.require(read_pinned(staging/'receipt.json',128*1024,self.timecheck)[0]==raw,
                           'Staged receipt changed')
            if video.get('published'):
                final_bytes,final_pin=read_pinned(staging/'boundary.mp4',64*hosted.core.MIB,self.timecheck)
                hosted.require(final_pin==pin and hashlib.sha256(final_bytes).hexdigest()==video['sha256'],
                               'Staged video changed')
                del final_bytes
            self.timecheck()
            # The upload allowlist sees no files until the whole set is verified.
            # No fallible publication work follows this one atomic directory rename.
            staging.rename(public)
        except BaseException as error:
            print(json.dumps({'observation_publication':'unavailable','error_type':type(error).__name__}))
            return code or 70
        return code


def file_pin(info):
    return info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns


def read_pinned(path,cap,check):
    check()
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        hosted.require(stat.S_ISREG(before.st_mode) and 0<before.st_size<=cap,'Publication type/size')
        with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(cap+1)
        check()
        hosted.require(file_pin(before)==file_pin(os.fstat(fd))==file_pin(path.lstat())
                       and len(raw)==before.st_size,'Publication input changed')
        return raw,file_pin(before)
    finally:os.close(fd)


if __name__=='__main__':
    hosted.HostedRecovery=ObservedRecovery
    sys.exit(hosted.main())
