#!/usr/bin/env python3
"""Offline guards for the explicit hosted qualification adapter."""
import copy
import hashlib
import importlib.util
import json
import os
import plistlib
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("qualification", Path(__file__).with_name("qualify-release.py"))
q = importlib.util.module_from_spec(spec); spec.loader.exec_module(q)
batch = q.load_module(Path(__file__).with_name("test-batch-simulator.py"), "qualification_test_batch")
BATCH_LOG = b"""Test Case '-[TripfolioTests.PlatformTests testVerifiedPurchaseAndRestoreFromLocalHistory]' started.
Test Case '-[TripfolioTests.PlatformTests testVerifiedPurchaseAndRestoreFromLocalHistory]' passed (1.000 seconds).
Test Case '-[TripfolioUITests.BatchImportUITests testRealFilesBatchRequiresEveryReviewAndPreservesOriginals]' started.
Test Case '-[TripfolioUITests.BatchImportUITests testRealFilesBatchRequiresEveryReviewAndPreservesOriginals]' passed (2.000 seconds).
"""
HEAD = "a" * 40
OWNED = "11111111-1111-4111-8111-111111111111"
EXISTING = "22222222-2222-4222-8222-222222222222"
ENV = {"GITHUB_ACTIONS": "true", "RUNNER_OS": "macOS", "GITHUB_EVENT_NAME": "workflow_dispatch",
       "GITHUB_WORKFLOW": "Release qualification", "GITHUB_JOB": "qualify",
       "GITHUB_REPOSITORY": "4alvit/travel-documents-ios", "GITHUB_SHA": HEAD,
       "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}


class Guards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def run_object(self, mode="batch"):
        return q.Qualification(self.root, mode, ENV)

    def fixture(self, mode="batch"):
        cases = list(batch.CASES) if mode == "batch" else ["Privacy/case" + str(n) + "()" for n in range(6)]
        source = {"head": HEAD, "status": "", "dirty": False}
        summary = {"status": "passed", "device": OWNED, "xcodebuild_returncode": 0,
                   "source_before": source, "source_after": copy.deepcopy(source),
                   "source_originals_unchanged": True, "fixture_cleanup": "removed only the uniquely created fixture folder",
                   "selected_method": None, "requests": {"match": 4, "nomatch": 1}}
        if mode == "batch": summary["execution_order"] = batch.execution_order(BATCH_LOG)
        result = {"result": "Passed", "totalTestCount": len(cases), "passedTests": len(cases),
                  "failedTests": 0, "skippedTests": 0, "expectedFailures": 0,
                  "runtimeWarnings": [], "testFailures": [],
                  "devicesAndConfigurations": [{"device": {"deviceId": OWNED, "osVersion": "26.2",
                                                            "osBuildNumber": "23C54", "architecture": "arm64"}}]}
        tree = {"testNodes": [{"nodeType": "Test Case", "nodeIdentifier": name, "result": "Passed"} for name in cases],
                "devices": [{"deviceId": OWNED, "platform": "iOS Simulator"}]}
        return summary, result, tree, cases

    def validate(self, mode, data):
        return q.validate_driver(mode, *data, OWNED, HEAD)

    def test_context_accepts_only_explicit_current_hosted_modes(self):
        for mode in q.MODES:
            self.assertEqual(q.context(mode, ENV)["GITHUB_SHA"], HEAD)
        for mode in ["all", "", "release", "batch; touch /tmp/bad"]:
            with self.assertRaises(RuntimeError): q.context(mode, ENV)
        for key, value in [("GITHUB_ACTIONS", "false"), ("RUNNER_OS", "Linux"),
                           ("GITHUB_EVENT_NAME", "pull_request"), ("GITHUB_WORKFLOW", "CI"),
                           ("GITHUB_JOB", "other"), ("GITHUB_REPOSITORY", "other/repo"),
                           ("GITHUB_SHA", "main"), ("GITHUB_RUN_ID", "../123"), ("GITHUB_RUN_ATTEMPT", "0")]:
            with self.subTest(key=key), self.assertRaises(RuntimeError): q.context("batch", {**ENV, key: value})

    def test_output_never_reuses_existing_or_symlinked_location(self):
        self.run_object()
        with self.assertRaises(FileExistsError): self.run_object()
        other = self.root / "other"; other.mkdir()
        (other / "build").symlink_to(self.root / "build", target_is_directory=True)
        with self.assertRaises(RuntimeError): q.Qualification(other, "batch", ENV)

    def test_runtime_is_exact_version_architecture_and_available(self):
        runtime = {"version": "18.5", "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-18-5",
                   "isAvailable": True, "supportedArchitectures": ["arm64"],
                   "supportedDeviceTypes": [{"identifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro"}]}
        self.assertEqual(q.choose_runtime({"runtimes": [runtime]}, "18.5", "arm64")[0], runtime["identifier"])
        for values, sdk, arch in [([runtime], "27.0", "arm64"), ([runtime], "18.5", "x86_64"),
                                  ([runtime, runtime], "18.5", "arm64"),
                                  ([{**runtime, "isAvailable": False}, runtime], "18.5", "arm64"),
                                  ([{**runtime, "supportedArchitectures": ["x86_64"]}, runtime], "18.5", "arm64"),
                                  ([{**runtime, "isAvailable": False}], "18.5", "arm64"),
                                  ([{**runtime, "supportedDeviceTypes": []}], "18.5", "arm64")]:
            with self.assertRaises(RuntimeError): q.choose_runtime({"runtimes": values}, sdk, arch)

    def test_runtime_evidence_distinguishes_sdk_and_checks_native_result(self):
        for mode in q.MODES:
            profile = q.toolchain_profile(mode)
            selection = {"identifier": "com.apple.CoreSimulator.SimRuntime.iOS-26-2", "version": "26.2",
                         "build": "23C54", "architecture": "arm64", "sdk_version": profile["sdk_version"],
                         "sdk_matched": True}
            result = self.fixture(mode)[1]
            q.validate_runtime_result(mode, selection, result)
            for key, value in [("version", "18.5"), ("sdk_version", "unknown"),
                               ("sdk_matched", 1), ("build", "wrong"), ("architecture", "x86_64")]:
                with self.subTest(mode=mode, key=key), self.assertRaises(RuntimeError):
                    q.validate_runtime_result(mode, {**selection, key: value}, result)

    def test_batch_order_must_match_the_original_bounded_log(self):
        proof = batch.execution_order(BATCH_LOG)
        self.assertEqual(q.validate_batch_order(BATCH_LOG, proof), proof)
        for recorded in [None, {}, {**proof, "hosted_pass_before_batch_start": False}]:
            with self.assertRaises(RuntimeError): q.validate_batch_order(BATCH_LOG, recorded)
        with self.assertRaises(RuntimeError):
            q.validate_batch_order(BATCH_LOG.replace(b"passed (2.000", b"failed (2.000"), proof)

    def test_source_requires_dispatched_head_and_clean_files(self):
        run = self.run_object(); (self.root / "file.swift").write_text("let a = 1\n")
        responses = {"rev-parse": HEAD, "status": "", "ls-files": "file.swift\0"}
        def command(label, argv, seconds=30): return "b" * 40 if argv[-1] == "HEAD^{tree}" else responses[argv[1]]
        run.command = command
        source = run.source("valid")
        self.assertEqual(source["head"], HEAD); self.assertIn("file.swift", source["files"])
        responses["status"] = " M file.swift"
        with self.assertRaises(RuntimeError): run.source("dirty")
        responses["status"] = ""; responses["rev-parse"] = "c" * 40
        with self.assertRaises(RuntimeError): run.source("wrong-head")
        responses["rev-parse"] = HEAD
        (self.root / "file.swift").unlink(); (self.root / "file.swift").symlink_to("missing")
        with self.assertRaises(RuntimeError): run.source("link")

    def test_driver_result_accepts_complete_exact_modes(self):
        for mode in q.MODES: self.validate(mode, self.fixture(mode))

    def test_driver_result_rejects_skips_failures_duplicates_and_other_device(self):
        changes = [lambda s,r,t: r.update(skippedTests=1), lambda s,r,t: r.update(failedTests=1),
                   lambda s,r,t: r.update(expectedFailures=1), lambda s,r,t: r.update(passedTests=True),
                   lambda s,r,t: r.update(runtimeWarnings=[{"message":"runtime issue"}]),
                   lambda s,r,t: r.update(testFailures=[{"failureText":"unexpected issue"}]),
                   lambda s,r,t: r.pop("testFailures"),
                   lambda s,r,t: r.update(runtimeWarnings=None),
                   lambda s,r,t: r.update(runtimeWarnings="[]"),
                   lambda s,r,t: t["testNodes"].append(copy.deepcopy(t["testNodes"][0])),
                   lambda s,r,t: t["testNodes"][0].update(result="Skipped"),
                   lambda s,r,t: t["devices"][0].update(deviceId=EXISTING),
                   lambda s,r,t: r["devicesAndConfigurations"][0]["device"].update(deviceId=EXISTING),
                   lambda s,r,t: s.update(status="failed"), lambda s,r,t: s.update(xcodebuild_returncode=65)]
        for mode in q.MODES:
            for change in changes:
                data = self.fixture(mode); change(*data[:3])
                with self.subTest(mode=mode,change=change), self.assertRaises(RuntimeError): self.validate(mode, data)

    def test_driver_source_and_specific_cleanup_or_biometrics_are_required(self):
        for mode in q.MODES:
            for mutation in [lambda s:s["source_after"].update(head="b"*40),
                             lambda s:s["source_before"].update(status=" M source"),
                             lambda s:s.pop("source_before")]:
                data=self.fixture(mode); mutation(data[0])
                with self.assertRaises(RuntimeError): self.validate(mode,data)
        data=self.fixture();data[0]["source_originals_unchanged"]=False
        with self.assertRaises(RuntimeError): self.validate("batch",data)
        for mutation in [lambda s:s.update(selected_method="testSubset"),lambda s:s["requests"].update(nomatch=0)]:
            data=self.fixture("biometrics"); mutation(data[0])
            with self.assertRaises(RuntimeError): self.validate("biometrics",data)

    def prepare_cleanup(self):
        run=self.run_object();run.owned=OWNED
        run.intent={"name":"unique", "runtime":"runtime", "type":"phone"}
        run.baseline={EXISTING:{"name":"user", "runtime":"other", "type":"pad", "state":"Booted"}}
        current={**copy.deepcopy(run.baseline), OWNED:{**run.intent,"state":"Booted"}}
        calls=[]; inventories=iter([current,copy.deepcopy(run.baseline)])
        run.inventory=lambda label:next(inventories)
        run.command=lambda label,argv,seconds=30:calls.append(argv) or ""
        return run,current,calls

    def test_cleanup_mutates_only_owned_uuid_and_proves_unchanged_baseline(self):
        run,_,calls=self.prepare_cleanup();run.cleanup()
        self.assertEqual(calls,[["xcrun","simctl","shutdown",OWNED],["xcrun","simctl","delete",OWNED]])
        self.assertTrue(run.report["cleanup_verified"])

    def test_cleanup_refuses_existing_or_changed_device_and_unknown_process(self):
        for mutation in [lambda r,c:setattr(r,"owned",EXISTING), lambda r,c:c[OWNED].update(name="other"),
                         lambda r,c:setattr(r.xcode,"unknown_spawn",True),
                         lambda r,c:r.xcode.active.update({123:SimpleNamespace(pid=123)})]:
            with tempfile.TemporaryDirectory(dir=self.root) as path:
                saved=self.root;self.root=Path(path)
                run,current,calls=self.prepare_cleanup();mutation(run,current)
                with self.assertRaises(RuntimeError):run.cleanup()
                self.assertFalse(calls);self.assertFalse(run.report["cleanup_verified"])
                self.root=saved

    def test_cleanup_rejects_changed_baseline_after_delete(self):
        run,current,calls=self.prepare_cleanup()
        values=iter([current,{EXISTING:{**run.baseline[EXISTING],"state":"Shutdown"}}])
        run.inventory=lambda label:next(values)
        with self.assertRaises(RuntimeError):run.cleanup()
        self.assertEqual(len(calls),2);self.assertFalse(run.report["cleanup_verified"])

    def failed_shutdown(self):
        run,current,calls=self.prepare_cleanup()
        observed={**copy.deepcopy(run.baseline),OWNED:{**run.intent,"state":"Shutdown"}}
        readings=[current,observed,copy.deepcopy(run.baseline)]; labels=[]
        def inventory(label):
            labels.append(label)
            return readings[len(labels)-1]
        def command(label,argv,seconds=30):
            calls.append((label,argv,seconds))
            if label=="shutdown": raise RuntimeError("shutdown RPC timeout")
            return ""
        run.inventory=inventory;run.command=command
        return run,calls,readings,labels

    def test_shutdown_error_uses_fresh_identity_before_deleting_stopped_device(self):
        run,calls,_,labels=self.failed_shutdown();deadline=run.cleanup_deadline
        run.cleanup()
        self.assertEqual([row[0] for row in calls],["shutdown","delete"])
        self.assertTrue(all(row[1][-1]==OWNED and row[2]==60 for row in calls))
        self.assertEqual(labels,["before-cleanup","after-shutdown-error","after-cleanup"])
        self.assertTrue(run.report["cleanup_verified"])
        self.assertIn("shutdown RPC timeout",run.report["errors"][0])
        self.assertEqual(run.commands.limit,deadline)
        self.assertEqual(run.cleanup_deadline,deadline)

    def test_shutdown_error_accepts_already_absent_owned_device_without_delete(self):
        run,calls,readings,labels=self.failed_shutdown()
        readings[1]=copy.deepcopy(run.baseline)
        run.cleanup()
        self.assertEqual([row[0] for row in calls],["shutdown"])
        self.assertEqual(labels[-1],"after-cleanup")
        self.assertTrue(run.report["cleanup_verified"])
        self.assertTrue(run.report["errors"])

    def test_shutdown_error_does_not_delete_a_still_booted_device(self):
        run,calls,readings,labels=self.failed_shutdown();readings[1][OWNED]["state"]="Booted"
        with self.assertRaisesRegex(RuntimeError,"not confirmed shut down"):run.cleanup()
        self.assertEqual([row[0] for row in calls],["shutdown"])
        self.assertEqual(labels,["before-cleanup","after-shutdown-error"])
        self.assertFalse(run.report["cleanup_verified"])

    def test_shutdown_error_does_not_delete_changed_identity(self):
        run,calls,readings,_=self.failed_shutdown();readings[1][OWNED]["name"]="another task"
        with self.assertRaisesRegex(RuntimeError,"identity changed"):run.cleanup()
        self.assertEqual([row[0] for row in calls],["shutdown"])
        self.assertFalse(run.report["cleanup_verified"])

    def test_shutdown_error_with_unresolved_process_cannot_query_or_delete_device(self):
        for owner_name,field in [("commands","active"),("commands","unknown_spawn"),
                                 ("xcode","active"),("xcode","unknown_spawn")]:
            with self.subTest(owner=owner_name,field=field),tempfile.TemporaryDirectory(dir=self.root) as path:
                saved=self.root;self.root=Path(path)
                try:
                    run,calls,_,labels=self.failed_shutdown();original=run.command
                    def command(*args):
                        owner=getattr(run,owner_name)
                        if field=="active":owner.active[123]=SimpleNamespace(pid=123)
                        else:owner.unknown_spawn=True
                        return original(*args)
                    run.command=command
                    with self.assertRaisesRegex(RuntimeError,"Unresolved process ownership"):run.cleanup()
                    self.assertEqual([row[0] for row in calls],["shutdown"])
                    self.assertEqual(labels,["before-cleanup"])
                    self.assertFalse(run.report["cleanup_verified"])
                finally:self.root=saved

    def test_shutdown_error_preserves_expired_cleanup_deadline(self):
        run,calls,_,labels=self.failed_shutdown();original=run.command
        def command(*args):
            run.cleanup_deadline=time.monotonic()-1
            return original(*args)
        run.command=command
        with self.assertRaisesRegex(RuntimeError,"deadline expired"):run.cleanup()
        self.assertEqual(labels,["before-cleanup"])
        self.assertEqual([row[0] for row in calls],["shutdown"])

    def test_shutdown_error_missing_device_still_requires_unchanged_baseline(self):
        run,calls,readings,_=self.failed_shutdown()
        readings[1]={EXISTING:{**run.baseline[EXISTING],"state":"Shutdown"}}
        with self.assertRaisesRegex(RuntimeError,"Baseline changed"):run.cleanup()
        self.assertEqual([row[0] for row in calls],["shutdown"])
        self.assertFalse(run.report["cleanup_verified"])

    def test_shutdown_error_does_not_hide_later_inventory_drift(self):
        run,calls,readings,_=self.failed_shutdown()
        readings[2]={EXISTING:{**run.baseline[EXISTING],"state":"Shutdown"}}
        with self.assertRaisesRegex(RuntimeError,"Baseline device inventory changed"):run.cleanup()
        self.assertEqual([row[0] for row in calls],["shutdown","delete"])
        self.assertFalse(run.report["cleanup_verified"])
        self.assertIn("shutdown RPC timeout",run.report["errors"][0])

    def test_recovered_shutdown_cleanup_never_turns_execution_into_pass(self):
        run,_,_,_=self.failed_shutdown()
        run.before={"head":HEAD};run.prepare=lambda:None
        run.source=lambda label:run.before;run.run_driver=lambda:None
        run.report.update(driver_capture_verified=True,products_verified=True,
                          batch_snapshot={"verified":True})
        with patch.object(run,"capture_original_result") as capture:
            self.assertEqual(run.execute(),1)
            capture.assert_not_called()
        self.assertTrue(run.report["cleanup_verified"])
        self.assertEqual(run.report["status"],"failed")

    def test_process_injection_is_local_and_registers_exactly_one_owned_xcodebuild(self):
        run=self.run_object();run.owned=OWNED;facade=run.facade();child=SimpleNamespace(pid=123)
        self.assertIsNot(facade,subprocess)
        argv=["xcodebuild","-destination","platform=iOS Simulator,id="+OWNED]
        with patch.object(q.subprocess,"Popen",return_value=child) as spawn:
            self.assertIs(facade.Popen(argv,cwd=self.root,start_new_session=True),child)
            self.assertIs(run.xcode.active[123],child)
            with self.assertRaises(RuntimeError):facade.Popen(argv,cwd=self.root,start_new_session=True)
            self.assertEqual(spawn.call_count,1)
        self.assertEqual(run.driver_calls,1);self.assertFalse(run.xcode.unknown_spawn)

    def test_driver_inventory_budget_is_narrow_and_preserves_caller_and_global_limits(self):
        run = self.run_object(); facade = run.facade()
        inventory = ["xcrun", "simctl", "list", "devices", "--json"]
        limits = (run.work_deadline, run.cleanup_deadline, run.commands.limit)
        cases = [(inventory, 120, 128), (tuple(inventory), 120, 128),
                 (inventory, 600, 128), (inventory, 12, 20),
                 (["xcrun", "simctl", "list", "devices", "available", "--json"], 120, 38),
                 (["xcrun", "simctl", "list", "runtimes", "--json"], 120, 38),
                 (["xcrun", "simctl", "shutdown", OWNED], 120, 38)]
        for argv, requested, expected in cases:
            with self.subTest(argv=argv, requested=requested), \
                 patch.object(run.commands, "command", return_value="{}") as command:
                result = facade.run(argv, cwd=self.root, timeout=requested, text=True)
                self.assertEqual(result.stdout, "{}")
                self.assertEqual(command.call_args.args[1:], (list(argv), expected))
                self.assertEqual((run.work_deadline, run.cleanup_deadline, run.commands.limit), limits)
        with patch.object(run.commands, "command") as command:
            with self.assertRaisesRegex(RuntimeError, "working directory"):
                facade.run(inventory, cwd=self.root / "other", timeout=120)
            command.assert_not_called()

    def test_unknown_spawn_withholds_device_cleanup(self):
        run=self.run_object();run.owned=OWNED;run.baseline={};facade=run.facade()
        with patch.object(q.subprocess,"Popen",side_effect=OSError("unknown acquisition")):
            with self.assertRaises(OSError):facade.Popen(["xcodebuild","platform=iOS Simulator,id="+OWNED],cwd=self.root,start_new_session=True)
        self.assertTrue(run.xcode.unknown_spawn)
        with self.assertRaises(RuntimeError):run.cleanup()

    def test_product_manifest_preserves_bytes_and_does_not_follow_links(self):
        app=self.root/"App.app";app.mkdir();(app/"payload").write_bytes(b"data");(app/"link").symlink_to("/outside")
        manifest=q.tree_manifest(app,lambda:None)
        self.assertEqual(manifest["./link"],{"kind":"link","target":"/outside"})
        self.assertEqual(manifest["./payload"]["bytes"],4)
        (app/"payload").write_bytes(b"changed")
        self.assertNotEqual(q.tree_manifest(app,lambda:None),manifest)

    def exercise_driver(self, *, skipped=False, runtime_warning=False, missing_warnings=False, root_extra=False, shared_failure=False):
        run=self.run_object();run.owned=OWNED;run.baseline={}
        run.report["runtime_selection"] = {"identifier": "com.apple.CoreSimulator.SimRuntime.iOS-26-2",
            "version": "26.2", "build": "23C54", "architecture": "arm64", "sdk_version": "26.2", "sdk_matched": True}
        summary,result,tree,cases=self.fixture()
        if skipped:result.update(passedTests=0,skippedTests=1)
        if runtime_warning:result["runtimeWarnings"]=[{"message":"Runtime issue"}]
        if missing_warnings:result.pop("runtimeWarnings")
        source=summary["source_before"]
        child=SimpleNamespace(pid=123,returncode=0,stdout=None,stderr=None,poll=lambda:0)
        events=[]
        module=SimpleNamespace(CASES=cases,execution_order=batch.execution_order,timestamp=lambda:"recorded")
        class Driver:
            def __init__(self,args):
                self.args=args
                self.directory=run.root/"build/BatchSimulator-fixture";self.directory.mkdir()
                self.fixture_directory=self.directory/"owned-fixtures"
                self.summary=copy.deepcopy(summary);self.actions=(self.directory/"actions.jsonl").open("w")
                (self.directory/"xcodebuild.log").write_bytes(BATCH_LOG)
            def prepare(self):events.append("prepare")
            def remaining(self):return 100
            def run_test(self):
                events.append("test")
                module.subprocess.Popen(["xcodebuild","-destination","platform=iOS Simulator,id="+OWNED],
                                        cwd=run.root,start_new_session=True)
                (self.directory/"xcresult-summary.json").write_text(json.dumps(result))
                (self.directory/"xcresult-tests.json").write_text(json.dumps(tree))
                if shared_failure: raise RuntimeError("original native failure")
            def verify_fixtures(self):events.append("verify-fixtures")
            def remove_fixtures(self):
                events.append("defer-root-cleanup")
                self.summary["fixture_destination_mode"]="native_root"
                self.summary["fixture_cleanup"]="native root retained for verified owned Simulator teardown"
            def source_snapshot(self):return copy.deepcopy(source)
            def save(self):(self.directory/"summary.json").write_text(json.dumps(self.summary))
        module.Driver=Driver
        run.xcode.ops=SimpleNamespace(now=time.monotonic,absent=lambda p:True,
                                     send=lambda *_:self.fail("Completed process needs no signal"))
        run.products=lambda driver:events.append("products")
        run.batch_snapshot=lambda driver:events.append("batch-snapshot")
        run.prepare_native_seed=lambda driver:events.append("native-seed")
        run.prepare_shared_build=lambda driver:events.append("shared-build")
        if shared_failure:
            run.shared_products={}
            def changed(*args):raise RuntimeError("shared product changed")
            run.observe_shared_build=changed
        def prepare_root(driver):
            self.assertTrue(driver.args.native_root)
            self.assertTrue(driver.args.native_seed)
            self.assertFalse(driver.args.native_folder)
            events.append("native-root")
            run.report["native_root"]={"verified_empty_before_seed":True}
        run.prepare_native_root=prepare_root
        def verify_root(driver):
            events.append("verify-complete-root")
            if root_extra: raise RuntimeError("Unexpected native seed destination entries")
        run.native_seed_files=verify_root
        run.prepare_native_folder=lambda driver:self.fail("Native root must not create a folder")
        with patch.object(q,"load_module",return_value=module),patch.object(q.subprocess,"Popen",return_value=child):
            if skipped or runtime_warning or root_extra or shared_failure:
                with self.assertRaisesRegex(RuntimeError,"original native failure" if shared_failure else ".*"):run.run_driver()
            else:run.run_driver()
        self.assertFalse(run.xcode.active)
        stop=run.xcode.report["commands"][0]["stop"]
        self.assertTrue(stop["group_absent"]);self.assertTrue(stop["leader_reaped"])
        self.assertEqual(events.count("test"),1)
        return run,events

    def test_shared_postcheck_cannot_mask_native_failure_or_skip_fixture_cleanup(self):
        run,events=self.exercise_driver(shared_failure=True)
        self.assertEqual(run.report["shared_build_errors"],["RuntimeError('shared product changed')"])
        self.assertIn("verify-complete-root",events)
        self.assertIn("defer-root-cleanup",events)
        self.assertNotIn("products",events)

    def test_original_driver_adapter_finishes_one_owned_process_before_product_acceptance(self):
        run,events=self.exercise_driver()
        self.assertEqual(events,["prepare","native-root","shared-build","native-seed","test","verify-fixtures","verify-complete-root","defer-root-cleanup","products","batch-snapshot"])
        self.assertTrue(run.report["driver_capture_verified"])

    def test_post_main_extra_root_entry_prevents_capture_after_owned_process_stop(self):
        run,events=self.exercise_driver(root_extra=True)
        self.assertIn("verify-complete-root",events)
        self.assertNotIn("products",events)
        self.assertNotIn("driver_capture_verified",run.report)
        self.assertNotIn("verified_after_main",run.report["native_root"])
        summary=json.loads((run.root/run.report["driver_directory"]/"summary.json").read_text())
        self.assertEqual(summary["status"],"failed")
        self.assertIn("Unexpected native seed destination entries",summary["error"])
        self.assertNotIn("native_root_post_main_verified",summary)

    def test_skipped_driver_result_never_reaches_product_acceptance(self):
        run,events=self.exercise_driver(skipped=True)
        self.assertNotIn("products",events);self.assertNotIn("driver_capture_verified",run.report)

    def test_actual_xcresult_runtime_warning_is_retained_and_prevents_acceptance(self):
        run,events=self.exercise_driver(runtime_warning=True)
        self.assertEqual(run.report["xcresult_issues"]["runtimeWarnings"],[{"message":"Runtime issue"}])
        self.assertNotIn("products",events);self.assertNotIn("driver_capture_verified",run.report)

    def test_missing_host_warning_field_is_not_reported_and_only_allows_capture(self):
        run,events=self.exercise_driver(missing_warnings=True)
        self.assertEqual(run.report["xcresult_issues"]["runtimeWarnings"],"not_reported")
        self.assertFalse(run.report["xcresult_issues"]["runtimeWarnings_reported"])
        self.assertTrue(run.report["driver_capture_verified"])
        self.assertEqual(run.report["status"],"running")

    def test_nested_runtime_warning_in_tree_fails_when_summary_does_not_report_warnings(self):
        for mode in q.MODES:
            data=self.fixture(mode);data[1].pop("runtimeWarnings")
            data[2]["testNodes"][0]["children"]=[{"nodeType":"Test Case Run","children":[
                {"nodeType":"Runtime Warning","name":"Observed runtime issue"}]}]
            with self.subTest(mode=mode), self.assertRaisesRegex(RuntimeError,"tree reported a runtime warning"):
                self.validate(mode,data)

    def test_execute_requires_both_products_and_final_device_cleanup(self):
        run=self.run_object();run.before={"head":HEAD}
        run.prepare=lambda:None;run.source=lambda label:run.before
        run.run_driver=lambda:run.report.update(driver_capture_verified=True,products_verified=True)
        run.cleanup=lambda:None
        self.assertEqual(run.execute(),1)
        self.assertEqual(run.report["status"],"failed")

    def prepared_capture(self, mode="batch"):
        run=self.run_object(mode);run.before={"head":HEAD}
        result=self.root/"build/OriginalDriver/Tests.xcresult"
        (result/"Data").mkdir(parents=True);(result/"Data/result").write_bytes(b"original result bytes")
        (result/"Info.plist").write_bytes(b"original result metadata")
        run.report["driver_directory"]="build/OriginalDriver"
        run.prepare=lambda:None;run.source=lambda label:run.before
        run.run_driver=lambda:run.report.update(driver_capture_verified=True,products_verified=True,
                                              batch_snapshot={"verified":True})
        run.cleanup=lambda:run.report.update(cleanup_verified=True)
        if mode == "batch":
            self.preparation_fixture(run)
            run.inspect_files_preparation()
            run.report["files_preparation_verified"] = True
            self.preparation_fixture(run, native_folder=True)
            run.inspect_files_preparation(native_folder=True)
            run.report["native_folder_verified"] = True
            self.preparation_fixture(run, native_seed=True)
            run.inspect_files_preparation(native_seed=True)
            run.report["native_seed_verified"] = True
        return run,result

    def preparation_fixture(self, run, native_seed=False, native_folder=False):
        prefix = "native-folder" if native_folder else "native-seed" if native_seed else "files-prepare"
        run.owned=OWNED;run.baseline={};run.intent={"name":"owned","runtime":"iOS-26-2","type":"iPhone"}
        run.report["runtime_selection"]={"identifier":"com.apple.CoreSimulator.SimRuntime.iOS-26-2",
            "version":"26.2","build":"23C54","architecture":"arm64","sdk_version":"26.2","sdk_matched":True}
        original=run.out/(prefix+".xcresult")
        (original/"Data").mkdir(parents=True);(original/"Data/result").write_bytes(b"original preparation")
        (original/"Info.plist").write_bytes(b"preparation metadata")
        _,summary,tree,_=self.fixture()
        summary.update(totalTestCount=1,passedTests=1)
        summary["devicesAndConfigurations"][0]["device"]["platform"]="iOS Simulator"
        case=q.FOLDER_CASE if native_folder else q.SEED_CASE if native_seed else q.PREPARE_CASE
        tree["testNodes"]=[{"nodeType":"Test Case","nodeIdentifier":case,"result":"Passed"}]
        def command(label, argv, seconds=30):
            kind=label.removeprefix(prefix+"-")
            self.assertIn(kind,("summary","tests"));self.assertEqual(seconds,60)
            self.assertIn(str(run.out/(prefix+"-inspection.xcresult")),[str(a) for a in argv])
            path=run.commands.out/(kind+".json")
            path.write_text(json.dumps(summary if kind=="summary" else tree))
            run.commands.report["commands"].append({"logs":{"stdout":str(path)}})
            return "this returned string is deliberately not the raw JSON"
        run.command=command
        return original,summary,tree

    def test_files_preparation_reads_copy_preserves_original_and_requires_exact_case_runtime(self):
        run=self.run_object();original,summary,tree=self.preparation_fixture(run)
        before=run.preparation_manifest(original)
        run.inspect_files_preparation()
        self.assertEqual(before,run.preparation_manifest(original))
        self.assertEqual(before,run.preparation_manifest(run.out/"files-prepare-inspection.xcresult"))
        self.assertTrue(run.report["files_preparation_original"]["unchanged_after_reader"])
        self.assertEqual(run.report["files_preparation_result"]["cases"],[q.PREPARE_CASE])
        for mutate in [lambda s,t:s.update(skippedTests=1),lambda s,t:s.pop("testFailures"),
                lambda s,t:s.update(runtimeWarnings=[{}]),lambda s,t:s.update(runtimeWarnings=None),
                lambda s,t:t["testNodes"].append({"nodeType":"Runtime Warning"}),
                lambda s,t:t["testNodes"][0].update(nodeIdentifier="Wrong/case()"),
                lambda s,t:t["testNodes"].append(t["testNodes"][0]),
                lambda s,t:t["devices"][0].update(deviceId=EXISTING),
                lambda s,t:s["devicesAndConfigurations"][0]["device"].update(osBuildNumber="wrong"),
                lambda s,t:s["devicesAndConfigurations"][0]["device"].update(osVersion="18.5"),
                lambda s,t:s["devicesAndConfigurations"][0]["device"].update(architecture="x86_64")]:
            s,t=copy.deepcopy(summary),copy.deepcopy(tree);mutate(s,t)
            with self.assertRaises(RuntimeError):q.validate_files_preparation(s,t,OWNED,run.report["runtime_selection"])

    def test_files_preparation_absent_warnings_are_pending_not_an_empty_array(self):
        run=self.run_object();_,summary,_=self.preparation_fixture(run);summary.pop("runtimeWarnings")
        run.inspect_files_preparation();r=run.report["files_preparation_result"]
        self.assertEqual(r["runtimeWarnings"],"not_reported");self.assertFalse(r["runtimeWarnings_reported"])
        self.assertEqual(r["independent_warning_and_pixel_review"],"pending")

    def test_files_preparation_rejects_original_mutation_and_invalid_raw_json(self):
        for fault in ("mutation","json","utf8"):
            with tempfile.TemporaryDirectory(dir=self.root) as directory:
                run=q.Qualification(directory,"batch",ENV);original,_,_=self.preparation_fixture(run)
                command=run.command
                def broken(label,argv,seconds=30):
                    result=command(label,argv,seconds)
                    if fault=="mutation":(original/"Data/result").write_bytes(b"mutated")
                    else:Path(run.commands.report["commands"][-1]["logs"]["stdout"]).write_bytes(
                        b'{"broken":}' if fault=="json" else b'\xff')
                    return result
                run.command=broken
                with self.assertRaises((RuntimeError,ValueError)):run.inspect_files_preparation()
                self.assertNotIn("files_preparation_verified",run.report)

    def test_files_preparation_manifest_rejects_links_and_oversize(self):
        run=self.run_object();original,_,_=self.preparation_fixture(run)
        target=original/"Data/result";target.unlink();target.symlink_to(run.out/"outside")
        with self.assertRaises(RuntimeError):run.preparation_manifest(original)
        target.unlink()
        with target.open("wb") as stream:stream.truncate(256*q.MIB+1)
        with self.assertRaises(RuntimeError):run.preparation_manifest(original)

    def test_files_preparation_once_owned_exact_command_and_scoped_environment(self):
        run=self.run_object();run.owned=OWNED;run.baseline={};run.intent={"name":"owned"}
        original_env=run.commands.ops.env;calls=[]
        def command(label,argv,seconds=30):
            calls.append((label,[str(v) for v in argv],seconds,dict(run.commands.ops.env)))
        run.command=command;run.inspect_files_preparation=lambda:None
        run.prepare_files_ui()
        self.assertIs(run.commands.ops.env,original_env);self.assertTrue(run.report["files_preparation_verified"])
        self.assertEqual(len(calls),1);label,argv,seconds,env=calls[0]
        self.assertEqual((label,seconds),("files-prepare-ui",600));self.assertEqual(argv[-1],"test")
        self.assertIn("platform=iOS Simulator,id="+OWNED,argv)
        self.assertEqual(argv[argv.index("-derivedDataPath")+1],
                         str(run.root/"build/QualificationPreparationDerivedData-123-1"))
        self.assertFalse(Path(argv[argv.index("-derivedDataPath")+1]).is_relative_to(run.out))
        self.assertEqual([v for v in argv if v.startswith("-only-testing:")],
                         ["-only-testing:TripfolioUITests/"+q.PREPARE_CASE.removesuffix("()")])
        for key in ["-default-test-execution-time-allowance","-maximum-test-execution-time-allowance"]:
            self.assertEqual(argv[argv.index(key)+1],"180")
        self.assertEqual(env["TEST_RUNNER_TRIPDOCKET_RECOVERY_PHASE"],"prepare")
        self.assertEqual(env["TEST_RUNNER_TRIPDOCKET_RECOVERY_UI"],"1")
        self.assertTrue(env["TEST_RUNNER_TRIPDOCKET_RECOVERY_FOLDER"].startswith("TripDocket-Recovery-"))
        with self.assertRaises(RuntimeError):run.prepare_files_ui()
        self.assertEqual(len(calls),1);self.assertEqual(run.driver_calls,0)

    def test_files_preparation_failure_remains_primary_and_restores_environment(self):
        run=self.run_object();run.owned=OWNED;run.baseline={};run.intent={"name":"owned"}
        previous=run.commands.ops.env
        run.command=lambda *a,**k:(_ for _ in ()).throw(RuntimeError("native failed"))
        run.inspect_files_preparation=lambda:(_ for _ in ()).throw(RuntimeError("inspection also failed"))
        with self.assertRaisesRegex(RuntimeError,"native failed"):run.prepare_files_ui()
        self.assertIs(run.commands.ops.env,previous)
        self.assertIn("inspection also failed",run.report["files_preparation_inspection_error"])
        self.assertNotIn("files_preparation_verified",run.report)

    def test_files_preparation_refuses_existing_device_expired_budget_and_unresolved_writer(self):
        for fault in ("existing","budget","writer","mode"):
            with tempfile.TemporaryDirectory(dir=self.root) as directory:
                run=q.Qualification(directory,"biometrics" if fault=="mode" else "batch",ENV)
                run.owned=OWNED;run.baseline={};run.intent={"name":"owned"};calls=[]
                run.command=lambda *a,**k:calls.append(a)
                run.inspect_files_preparation=lambda:self.fail("Inspection must not run")
                if fault=="existing":run.baseline[OWNED]={}
                if fault=="budget":run.work_deadline=time.monotonic()+q.PREPARE_SECONDS+q.MODES["batch"][1]
                if fault=="writer":run.commands.unknown_spawn=True
                with self.assertRaises(RuntimeError):run.prepare_files_ui()
                if fault!="writer":self.assertFalse(calls)
                self.assertNotIn("files_preparation_verified",run.report)

    def test_final_capture_requires_preparation_and_rechecks_its_original_after_cleanup(self):
        run,_=self.prepared_capture();run.report.pop("files_preparation_verified")
        self.assertEqual(run.execute(),1);self.assertEqual(run.report["status"],"failed")
        run.report["files_preparation_verified"]=True
        (run.out/"files-prepare.xcresult/Data/result").write_bytes(b"late mutation")
        with self.assertRaisesRegex(RuntimeError,"changed before final capture"):run.capture_original_result()

    def test_successful_capture_is_pending_review_and_binds_unchanged_original_bytes(self):
        for mode in q.MODES:
            with tempfile.TemporaryDirectory(dir=self.root) as directory:
                saved=self.root;self.root=Path(directory)
                run,result=self.prepared_capture(mode)
                before={str(p.relative_to(result)):p.read_bytes() for p in result.rglob("*") if p.is_file()}
                self.assertEqual(run.execute(),0)
                self.assertEqual(run.report["status"],"captured_pending_review")
                proof=run.report["original_xcresult"];raw=(run.out/proof["manifest"]).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(),proof["manifest_sha256"])
                manifest=json.loads(raw)
                self.assertEqual(manifest["./Data/result"]["sha256"],hashlib.sha256(before["Data/result"]).hexdigest())
                self.assertEqual(before,{str(p.relative_to(result)):p.read_bytes() for p in result.rglob("*") if p.is_file()})
                self.root=saved

    def test_result_manifest_failure_never_becomes_a_successful_capture(self):
        run,result=self.prepared_capture();(result/"Info.plist").unlink()
        self.assertEqual(run.execute(),1)
        self.assertEqual(run.report["status"],"failed")
        self.assertNotIn("original_xcresult",run.report)

    def test_result_capture_refuses_incomplete_cleanup_and_oversized_bundle(self):
        run,result=self.prepared_capture()
        with self.assertRaises(RuntimeError):run.capture_original_result()
        run.report["cleanup_verified"]=True
        with (result/"Data/result").open("wb") as stream:stream.truncate(256*q.MIB+1)
        with self.assertRaisesRegex(RuntimeError,"byte cap"):run.capture_original_result()
        self.assertNotIn("original_xcresult",run.report)

    def test_result_capture_rejects_links_instead_of_binding_external_bytes(self):
        run,result=self.prepared_capture();run.report["cleanup_verified"]=True
        (result/"Data/link").symlink_to(self.root/"outside")
        with self.assertRaisesRegex(RuntimeError,"unsupported links"):run.capture_original_result()
        self.assertNotIn("original_xcresult",run.report)

    def snapshot_fixture(self):
        root=Path(tempfile.mkdtemp(dir=self.root));run=q.Qualification(root,"batch",ENV);run.owned=OWNED
        home=root/"home"
        container=home/"Library/Developer/CoreSimulator/Devices"/OWNED/"data/Containers/Data/Application"/EXISTING
        generation="33333333-3333-4333-8333-333333333333"
        library=container/"Library/Application Support/TripfolioUITesting"
        directory=library/generation;directory.mkdir(parents=True)
        (library/"active.json").write_text(json.dumps({"formatVersion":1,"generation":generation}))
        driver=SimpleNamespace(directory=root/"driver",summary={"fixtures":[]})
        (driver.directory/"fixtures").mkdir(parents=True)
        catalog={"schemaVersion":1,"trips":[{"id":OWNED}],"travelers":[],"documents":[]}
        for n,name in enumerate(["synthetic-ticket.pdf","synthetic-insurance.pdf","demo.pdf"],1):
            identifier=f"00000000-0000-4000-8000-{n:012d}";data=("synthetic "+name).encode()
            document={"id":identifier,"tripID":OWNED,"originalFilename":name,"storedFilename":identifier+".pdf",
                      "byteCount":len(data),"sha256":hashlib.sha256(data).hexdigest()}
            catalog["documents"].append(document);(directory/document["storedFilename"]).write_bytes(data)
            if n<3:
                (driver.directory/"fixtures"/name).write_bytes(data)
                driver.summary["fixtures"].append({"name":name,"bytes":len(data),"sha256":document["sha256"]})
        (directory/"catalog.json").write_text(json.dumps(catalog))
        calls=[]
        run.command=lambda label,argv,seconds=30:calls.append(argv) or str(container)
        return run,driver,home,library,directory,catalog,calls

    def test_batch_snapshot_keeps_exact_fixture_and_final_catalog_bytes(self):
        run,driver,home,library,directory,catalog,calls=self.snapshot_fixture()
        with patch.object(Path,"home",return_value=home):run.batch_snapshot(driver)
        receipt=run.report["batch_snapshot"];self.assertTrue(receipt["verified"])
        self.assertEqual(calls,[["xcrun","simctl","get_app_container",OWNED,q.APP_ID,"data"]])
        saved=run.out/"BatchLibrary"
        manifest=json.loads((saved/"manifest.json").read_text())
        self.assertEqual(len(manifest["fixture_matches"]),2)
        self.assertIn("no pre-run snapshot",manifest["other_originals"])
        self.assertEqual((saved/"catalog.json").read_bytes(),(directory/"catalog.json").read_bytes())
        for document in catalog["documents"]:
            name=document["storedFilename"]
            self.assertEqual((saved/name).read_bytes(),(directory/name).read_bytes())

    def test_batch_snapshot_rejects_paths_symlinks_and_changed_hashes(self):
        for mutation in ("generation","stored-path","symlink-file","symlink-directory","hash","fixture-hash","fixture-copy"):
            run,driver,home,library,directory,catalog,_=self.snapshot_fixture()
            document=catalog["documents"][0];original=directory/document["storedFilename"]
            if mutation=="generation":(library/"active.json").write_text('{"formatVersion":1,"generation":"../other"}')
            elif mutation=="stored-path":document["storedFilename"]="../outside.pdf"
            elif mutation=="symlink-file":original.unlink();original.symlink_to(driver.directory/"fixtures/synthetic-ticket.pdf")
            elif mutation=="symlink-directory":
                renamed=directory.with_name("saved");directory.rename(renamed);directory.symlink_to(renamed,target_is_directory=True)
            elif mutation=="hash":original.write_bytes(b"changed original")
            elif mutation=="fixture-hash":driver.summary["fixtures"][0]["sha256"]="0"*64
            elif mutation=="fixture-copy":(driver.directory/"fixtures/synthetic-ticket.pdf").write_bytes(b"changed fixture")
            (directory/"catalog.json").write_text(json.dumps(catalog))
            with self.subTest(mutation=mutation),patch.object(Path,"home",return_value=home):
                with self.assertRaises((RuntimeError,ValueError,OSError)):run.batch_snapshot(driver)
                self.assertNotIn("batch_snapshot",run.report)

    def test_batch_snapshot_rejects_item_document_and_library_limits(self):
        for mutation in ("items","document","library","boolean-size"):
            run,driver,home,_,directory,catalog,_=self.snapshot_fixture()
            if mutation=="items":catalog["documents"]*=334
            elif mutation=="document":catalog["documents"][0]["byteCount"]=16*q.MIB+1
            elif mutation=="boolean-size":catalog["documents"][0]["byteCount"]=True
            else:
                catalog["documents"]=[{**catalog["documents"][0],"id":f"00000000-0000-4000-8000-{n:012d}",
                    "storedFilename":f"00000000-0000-4000-8000-{n:012d}.pdf","byteCount":16*q.MIB} for n in range(5)]
            (directory/"catalog.json").write_text(json.dumps(catalog))
            with self.subTest(mutation=mutation),patch.object(Path,"home",return_value=home):
                with self.assertRaisesRegex(RuntimeError,"limit"):run.batch_snapshot(driver)
                self.assertNotIn("batch_snapshot",run.report)

    def test_bounded_read_rejects_byte_growth_and_links(self):
        directory=self.root/"bounded";directory.mkdir();path=directory/"file";path.write_bytes(b"12345")
        with self.assertRaisesRegex(RuntimeError,"limit"):q.bounded_read(directory,"file",4,lambda:None)
        path.write_bytes(b"1234");read=os.read;grew=False
        def grow(fd,size):
            nonlocal grew
            if not grew:
                grew=True
                with path.open("ab") as stream:stream.write(b"5")
            return read(fd,size)
        with patch.object(q.os,"read",side_effect=grow):
            with self.assertRaisesRegex(RuntimeError,"limit"):q.bounded_read(directory,"file",4,lambda:None)
        path.unlink();path.symlink_to("/outside")
        with self.assertRaisesRegex(RuntimeError,"link"):q.bounded_read(directory,"file",10,lambda:None)
        for relative in ["../file","/file","part//file","part/./file","part\\file"]:
            with self.assertRaises(RuntimeError):q.bounded_read(directory,relative,10,lambda:None)

    def test_container_path_rejects_other_device_noncanonical_uuid_and_extra_depth(self):
        run,_,home,_,directory,_,_=self.snapshot_fixture()
        container=directory.parents[3]
        with patch.object(Path,"home",return_value=home):
            self.assertEqual(run.container_path(str(container),"Data","Application"),container)
            for value in [str(directory),str(home),str(container).replace(OWNED,EXISTING)]:
                with self.assertRaises((RuntimeError,ValueError,OSError)):run.container_path(value,"Data","Application")
            invalid=container.with_name("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");invalid.mkdir()
            with self.assertRaises(RuntimeError):run.container_path(str(invalid),"Data","Application")

    def test_batch_snapshot_requires_one_match_for_each_fixture(self):
        for duplicate in [False,True]:
            run,driver,home,_,directory,catalog,_=self.snapshot_fixture()
            catalog["documents"][1]["originalFilename"]="synthetic-ticket.pdf" if duplicate else "wrong.pdf"
            (directory/"catalog.json").write_text(json.dumps(catalog))
            with patch.object(Path,"home",return_value=home):
                with self.assertRaises(RuntimeError):run.batch_snapshot(driver)
            self.assertNotIn("batch_snapshot",run.report)

    def schemas(self):
        fixtures = Path(__file__).parent / "fixtures/xcresult-xcode-26.2"
        return ((fixtures / "summary-schema.txt").read_bytes(), (fixtures / "tests-schema.json").read_bytes())

    def test_exact_producer_documents_are_recognized_without_json_normalization(self):
        summary, tests = self.schemas()
        self.assertTrue(q.validate_schemas(summary, tests)["documentation_verified"])
        with self.assertRaises(json.JSONDecodeError): json.loads(summary)
        self.assertIn("Tests", json.loads(tests)["schemas"])
        self.assertNotIn(b'"runtimeWarnings"', summary)
        # Identity of stale documentation never substitutes for actual evidence.
        data = self.fixture(); data[1].pop("testFailures")
        with self.assertRaises(RuntimeError): self.validate("batch", data)

    def test_changed_producer_docs_are_rejected_even_if_valid_json(self):
        for index in (0, 1):
            for replacement in (b"{}", b'{"runtimeWarnings":[]}', self.schemas()[index] + b"\n",
                                self.schemas()[index].replace(b'"deviceId"', b'"otherId"')):
                documents = list(self.schemas()); documents[index] = replacement
                with self.subTest(index=index), self.assertRaises(RuntimeError): q.validate_schemas(*documents)

    def test_schema_identity_rejects_wrong_types_empty_oversized_and_swapped_docs(self):
        for malformed in ({}, [], None, "text", b"", b"x" * (q.MIB + 1)):
            with self.assertRaises(RuntimeError): q.validate_schemas(malformed, self.schemas()[1])
        with self.assertRaises(RuntimeError): q.validate_schemas(*reversed(self.schemas()))

    def test_preflight_captures_exact_raw_schemas_before_any_device_action(self):
        run = self.run_object("biometrics"); calls = []; schemas = self.schemas()
        outputs = {kind: schemas[n].decode() for n, kind in enumerate(("summary", "tests"))}
        def command(label, argv, seconds=30):
            calls.append(argv); return outputs[argv[4]]
        run.command = command; run.preflight_schemas()
        for kind in ("summary", "tests"):
            self.assertIn(["xcrun", "xcresulttool", "get", "test-results", kind, "--schema"], calls)
            raw = (run.out / ("xcresult-schema-" + kind + ".json")).read_bytes()
            self.assertEqual(raw, outputs[kind].encode())
            self.assertEqual(run.report["xcresult_schema"]["sha256"][kind], hashlib.sha256(raw).hexdigest())
        self.assertEqual(len(calls), 2); self.assertIsNone(run.owned)

    def test_unrecognized_schema_stops_prepare_before_project_or_device_mutation(self):
        run = self.run_object("biometrics"); run.source = lambda label: {"head": HEAD, "tree": "b" * 40}; calls = []
        schemas = self.schemas()
        outputs = {"xcode": q.XCODE_VERSION, "developer": q.DEVELOPER_DIR, "sdk": "26.2", "architecture": "arm64",
                   "xcresult-schema-summary": schemas[0].decode() + "\n", "xcresult-schema-tests": schemas[1].decode()}
        def command(label, argv, seconds=30):
            calls.append(argv); return outputs[label]
        run.command = command
        with patch.dict(q.os.environ, {"DEVELOPER_DIR": q.DEVELOPER_DIR}):
            with self.assertRaises(RuntimeError): run.prepare()
        self.assertFalse(any("simctl" in argv or "xcodegen" in argv for argv in calls))
        self.assertIsNone(run.owned); self.assertIsNone(run.baseline)

    def test_batch_preflight_requires_the_exact_26_2_schema_documents(self):
        run = self.run_object(); calls = []; schemas = self.schemas()
        outputs = {kind: schemas[n].decode() for n, kind in enumerate(("summary", "tests"))}
        run.command = lambda label, argv, seconds=30: calls.append(argv) or outputs[argv[4]]
        run.preflight_schemas()
        self.assertEqual(calls, [["xcrun", "xcresulttool", "get", "test-results", kind, "--schema"]
                                 for kind in ("summary", "tests")])
        report = run.report["xcresult_schema"]
        self.assertTrue(report["documentation_verified"])
        self.assertEqual(report["selection"], "pinned-toolchain-default")
        self.assertIn("Independent pinned-reader review", report["runtime_evidence"])
        for n, kind in enumerate(("summary", "tests")):
            self.assertEqual((run.out / ("xcresult-schema-" + kind + ".json")).read_bytes(), schemas[n])
            self.assertEqual(report["sha256"][kind], hashlib.sha256(schemas[n]).hexdigest())
        self.assertFalse((run.out / "xcresulttool-version.txt").exists())
        self.assertIsNone(run.owned)
        self.assertTrue(q.validate_schemas(*schemas, mode="batch")["documentation_verified"])

    def test_batch_preflight_rejects_unknown_documents_before_device_actions(self):
        run = self.run_object()
        old_version = (Path(__file__).parent / "fixtures/xcresult-xcode-16.4/xcresulttool-version.txt").read_text()
        for raw in ["", old_version, "{}", self.schemas()[0].decode() + "\n"]:
            run.command = lambda *args: raw
            with self.subTest(raw=raw), self.assertRaisesRegex(RuntimeError, "schema"):
                run.preflight_schemas()
            self.assertNotIn("xcresult_schema", run.report)
            self.assertIsNone(run.owned)

    def test_mode_profiles_reject_wrong_xcode_sdk_or_environment_before_native_work(self):
        for mode in q.MODES:
            profile = q.toolchain_profile(mode)
            for key, value in [("xcode", "Xcode 16.4\nBuild version 16F6"), ("sdk", "18.5"),
                               ("environment", "/Applications/Xcode_16.4.app/Contents/Developer")]:
                directory = self.root / (mode + key); directory.mkdir()
                run = q.Qualification(directory, mode, ENV)
                run.source = lambda label: {"head": HEAD, "tree": "b" * 40}
                outputs = {"xcode": profile["xcode_version"], "developer": profile["developer_dir"],
                           "sdk": profile["sdk_version"], "architecture": "arm64"}
                if key != "environment": outputs[key] = value
                calls = []
                def command(label, argv, seconds=30):
                    calls.append(argv); return outputs[label]
                run.command = command
                with patch.dict(q.os.environ, {"DEVELOPER_DIR": value if key == "environment" else profile["developer_dir"]}):
                    with self.subTest(mode=mode, key=key), self.assertRaisesRegex(RuntimeError, "pinned"):
                        run.prepare()
                self.assertFalse(any("simctl" in argv or "xcodegen" in argv or "xcresulttool" in argv for argv in calls))
                self.assertIsNone(run.owned)
        with self.assertRaises(RuntimeError): q.toolchain_profile("unknown")

    def test_mode_profiles_keep_default_26_2_schema_contract(self):
        batch, bio = q.toolchain_profile("batch"), q.toolchain_profile("biometrics")
        self.assertEqual(batch, bio)
        self.assertEqual((batch["xcode_version"], batch["sdk_version"]), ("Xcode 26.2\nBuild version 17C52", "26.2"))
        self.assertEqual(batch["runtime_version"], "26.2")
        self.assertEqual(batch["schema_documents"], q.SCHEMA_DOCUMENTS)
        self.assertEqual((bio["xcode_version"], bio["developer_dir"]), (q.XCODE_VERSION, q.DEVELOPER_DIR))
        self.assertEqual(bio["runtime_version"], bio["sdk_version"])
        self.assertEqual(bio["schema_documents"], q.SCHEMA_DOCUMENTS)
        self.assertTrue(q.validate_schemas(*self.schemas())["documentation_verified"])

    def test_each_exact_profile_completes_its_preflight_before_discovery(self):
        for mode in q.MODES:
            directory = self.root / mode; directory.mkdir()
            run = q.Qualification(directory, mode, ENV)
            run.source = lambda label: {"head": HEAD, "tree": "b" * 40}
            profile = q.toolchain_profile(mode); schemas = self.schemas(); calls = []
            outputs = {"xcode": profile["xcode_version"], "developer": profile["developer_dir"],
                       "sdk": profile["sdk_version"], "architecture": "arm64", "generate-project": "",
                       "xcresulttool-version": (profile["xcresulttool_version"] or "") + "\n",
                       "xcresult-schema-summary": schemas[0].decode(), "xcresult-schema-tests": schemas[1].decode()}
            def command(label, argv, seconds=30):
                calls.append(label)
                if label == "runtimes": raise RuntimeError("Discovery boundary reached")
                return outputs[label]
            run.command = command
            with patch.dict(q.os.environ, {"DEVELOPER_DIR": profile["developer_dir"]}):
                with self.assertRaisesRegex(RuntimeError, "Discovery boundary reached"): run.prepare()
            self.assertEqual(calls[-2:], ["generate-project", "runtimes"])
            self.assertNotIn("xcresulttool-version", calls)
            self.assertIn("xcresult-schema-summary", calls)
            self.assertIn("xcresult-schema-tests", calls)
            self.assertIsNone(run.owned)

    def test_prepare_records_runtime_independently_from_compiler_sdk(self):
        for mode in q.MODES:
            directory = self.root / mode; directory.mkdir()
            run = q.Qualification(directory, mode, ENV)
            run.source = lambda label: {"head": HEAD, "tree": "b" * 40}
            run.preflight_schemas = lambda: None
            profile = q.toolchain_profile(mode)
            runtimes = {"runtimes": [{"version": version, "buildversion": build,
                "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-" + version.replace(".", "-"),
                "isAvailable": True, "supportedArchitectures": ["arm64"],
                "supportedDeviceTypes": [{"identifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro"}]}
                for version, build in [("18.5", "22F77"), ("26.2", "23C54")]]}
            outputs = {"xcode": profile["xcode_version"], "developer": profile["developer_dir"],
                "sdk": profile["sdk_version"], "architecture": "arm64", "generate-project": "",
                "runtimes": json.dumps(runtimes)}
            run.command = lambda label, argv, seconds=30: outputs[label]
            run.inventory = lambda label: (_ for _ in ()).throw(RuntimeError("Before any device mutation"))
            with patch.dict(q.os.environ, {"DEVELOPER_DIR": profile["developer_dir"]}):
                with self.assertRaisesRegex(RuntimeError, "Before any device mutation"): run.prepare()
            self.assertEqual(run.report["runtime_selection"], {
                "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-26-2", "version": "26.2", "build": "23C54",
                "architecture": "arm64", "sdk_version": profile["sdk_version"], "sdk_matched": True})
            self.assertIsNone(run.owned)

    def test_schema_cli_uses_only_files_and_rejects_mixed_execution_mode(self):
        paths = []
        for n, schema in enumerate(self.schemas()):
            path = self.root / (str(n) + ".json"); path.write_bytes(schema); paths.append(str(path))
        with patch.object(q, "Qualification", side_effect=AssertionError("Native run not allowed")):
            with patch.object(q.sys, "argv", ["qualify-release.py", "--validate-schemas", *paths]):
                self.assertEqual(q.main(), 0)
            with patch.object(q.sys, "argv", ["qualify-release.py", "--mode", "batch", "--validate-schemas", *paths]):
                with self.assertRaises(SystemExit): q.main()
            with patch.object(q.sys, "argv", ["qualify-release.py", "--schema-mode", "batch", "--validate-schemas", *paths]):
                self.assertEqual(q.main(), 0)
            with patch.object(q.sys, "argv", ["qualify-release.py", "--mode", "batch", "--schema-mode", "biometrics"]):
                with self.assertRaises(SystemExit): q.main()
        link = self.root / "link"; link.symlink_to(paths[0])
        with patch.object(q.sys, "argv", ["qualify-release.py", "--validate-schemas", str(link), paths[1]]):
            with self.assertRaises(RuntimeError): q.main()

    def seed_fixture(self):
        run=self.run_object();run.owned=OWNED;run.baseline={};run.intent={"name":"owned"}
        run.report["files_preparation_verified"]=True
        run.report["native_folder_verified"]=True
        derived=run.root/"build/QualificationPreparationDerivedData-123-1";derived.mkdir()
        run.report["files_preparation"]={"derived_data":str(derived.relative_to(run.root))}
        group=self.root/"group";provider=group/"File Provider Storage";provider.mkdir(parents=True)
        token="12345678-1234-4234-8234-123456789abc"
        owned=provider/("TripDocket-Batch-QA-"+token);owned.mkdir()
        directory=run.root/"build/driver";copies=directory/"fixtures";copies.mkdir(parents=True)
        fixtures=[]
        for name,title in [("synthetic-ticket.pdf","SYNTHETIC TICKET"),("synthetic-insurance.pdf","SYNTHETIC INSURANCE")]:
            data=batch.pdf(title);(copies/name).write_bytes(data)
            fixtures.append({"name":name,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()})
        driver=SimpleNamespace(token=token,folder_name=owned.name,fixture_directory=owned,directory=directory,
            provider_identity=(provider.stat().st_dev,provider.stat().st_ino),
            fixture_identity=(owned.stat().st_dev,owned.stat().st_ino),summary={"fixtures":fixtures},
            deadline=time.monotonic()+1200,record=lambda *a,**k:None)
        driver.remaining=lambda:driver.deadline-time.monotonic()
        def container(value,*kind):
            self.assertEqual((value,kind),(str(group),("Shared","AppGroup")))
            return group
        run.container_path=container
        driver.qualified_build=derived
        run.report["shared_build"]={"observations":{"before_seed":{}}}
        run.observe_shared_build=lambda driver,label:None
        return run,driver

    def test_seed_destination_is_empty_then_exact_bytes_with_pinned_identity(self):
        run,driver=self.seed_fixture();run.native_seed_files(driver,empty=True)
        with self.assertRaises(RuntimeError):run.native_seed_files(driver)
        for item in driver.summary["fixtures"]:
            (driver.fixture_directory/item["name"]).write_bytes((driver.directory/"fixtures"/item["name"]).read_bytes())
        run.native_seed_files(driver)
        with self.assertRaises(RuntimeError):run.native_seed_files(driver,empty=True)
        driver.fixture_identity=(0,0)
        with self.assertRaisesRegex(RuntimeError,"identity changed"):run.native_seed_files(driver)

    def test_seed_destination_rejects_hash_link_extra_file_and_bad_token(self):
        run,driver=self.seed_fixture();owned=driver.fixture_directory
        for item in driver.summary["fixtures"]:
            (owned/item["name"]).write_bytes((driver.directory/"fixtures"/item["name"]).read_bytes())
        target=owned/"synthetic-ticket.pdf";original=target.read_bytes()
        target.write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError,"original bytes"):run.native_seed_files(driver)
        target.unlink();target.symlink_to(driver.directory/"fixtures/synthetic-ticket.pdf")
        with self.assertRaises((RuntimeError,OSError)):run.native_seed_files(driver)
        target.unlink();target.write_bytes(original);(owned/"extra").write_bytes(b"")
        with self.assertRaises(RuntimeError):run.native_seed_files(driver)
        (owned/"extra").unlink();driver.token=driver.token.upper()
        with self.assertRaises(RuntimeError):run.native_seed_files(driver)

    def test_seed_one_owned_invocation_consumes_existing_clock_and_restores_environment(self):
        run,driver=self.seed_fixture();deadline=driver.deadline;previous=run.commands.ops.env;calls=[]
        def command(label,argv,seconds):
            calls.append((label,[str(x) for x in argv],seconds,dict(run.commands.ops.env)))
            for item in driver.summary["fixtures"]:
                (driver.fixture_directory/item["name"]).write_bytes((driver.directory/"fixtures"/item["name"]).read_bytes())
        run.command=command;run.inspect_files_preparation=lambda native_seed=False:self.assertTrue(native_seed)
        run.prepare_native_seed(driver)
        self.assertEqual(driver.deadline,deadline);self.assertIs(run.commands.ops.env,previous)
        self.assertTrue(run.report["native_seed_verified"]);self.assertEqual(len(calls),1)
        label,argv,seconds,env=calls[0]
        self.assertEqual((label,seconds),("native-seed-ui",300))
        self.assertEqual(argv[-1], "test-without-building")
        self.assertIn("platform=iOS Simulator,id="+OWNED,argv)
        self.assertEqual([x for x in argv if x.startswith("-only-testing:")],
                         ["-only-testing:TripfolioUITests/"+q.SEED_CASE.removesuffix("()")])
        self.assertEqual(argv[argv.index("-maximum-test-execution-time-allowance")+1],"180")
        self.assertEqual(env["TEST_RUNNER_TRIPDOCKET_NATIVE_SEED_TOKEN"],driver.token)
        self.assertEqual(env["TEST_RUNNER_TRIPDOCKET_BATCH_FOLDER"],driver.folder_name)
        self.assertNotIn("TEST_RUNNER_TRIPDOCKET_RECOVERY_UI",env)
        with self.assertRaises(RuntimeError):run.prepare_native_seed(driver)
        self.assertEqual(len(calls),1);self.assertEqual(run.driver_calls,0)

    def test_seed_native_failure_is_primary_even_with_invalid_inspection(self):
        run,driver=self.seed_fixture();previous=run.commands.ops.env
        def fail(*a,**k):raise RuntimeError("native seed failed")
        def bad(*a,**k):raise RuntimeError("inspection failed")
        run.command=fail;run.inspect_files_preparation=bad
        with self.assertRaisesRegex(RuntimeError,"native seed failed"):run.prepare_native_seed(driver)
        self.assertIs(run.commands.ops.env,previous)
        self.assertIn("inspection failed",run.report["native_seed_inspection_error"])
        self.assertNotIn("native_seed_verified",run.report)

    def test_seed_rejects_wrong_owner_exhausted_shared_deadline_and_unresolved_writer(self):
        for fault in ("owner","driver-deadline","outer-deadline","writer","mode","prep","folder"):
            with tempfile.TemporaryDirectory() as temporary:
                saved=self.root;self.root=Path(temporary).resolve()
                try:run,driver=self.seed_fixture()
                finally:self.root=saved
                if fault=="owner":run.baseline[OWNED]={}
                elif fault=="driver-deadline":driver.deadline=time.monotonic()+900
                elif fault=="outer-deadline":run.work_deadline=time.monotonic()+900
                elif fault=="writer":run.commands.unknown_spawn=True
                elif fault=="mode":run.mode="biometrics"
                elif fault=="folder":run.report["native_folder_verified"]=False
                else:run.report["files_preparation_verified"]=False
                run.command=lambda *a,**k:self.fail("Native command must not start")
                with self.subTest(fault=fault),self.assertRaises(RuntimeError):run.prepare_native_seed(driver)

    def test_seed_result_requires_its_own_exact_case_and_preserves_original(self):
        run=self.run_object();original,summary,tree=self.preparation_fixture(run,native_seed=True)
        before=run.preparation_manifest(original);run.inspect_files_preparation(native_seed=True)
        self.assertEqual(run.preparation_manifest(original),before)
        self.assertEqual(run.report["native_seed_result"]["cases"],[q.SEED_CASE])
        for fault in ("case","skip","warnings","missing-failures","runtime"):
            result=copy.deepcopy(summary);nodes=copy.deepcopy(tree)
            if fault=="case":nodes["testNodes"][0]["nodeIdentifier"]=q.PREPARE_CASE
            elif fault=="skip":result.update(skippedTests=1,passedTests=0)
            elif fault=="warnings":result["runtimeWarnings"]=[{"message":"warning"}]
            elif fault=="missing-failures":result.pop("testFailures")
            else:result["devicesAndConfigurations"][0]["device"]["osVersion"]="18.5"
            with self.subTest(fault=fault),self.assertRaises(RuntimeError):
                q.validate_files_preparation(result,nodes,OWNED,run.report["runtime_selection"],q.SEED_CASE)

    def test_final_capture_requires_native_seed_and_rechecks_seed_bytes_after_cleanup(self):
        run,_=self.prepared_capture();run.report["cleanup_verified"]=True
        run.report.pop("native_seed_verified")
        with self.assertRaisesRegex(RuntimeError,"Missing verified"):run.capture_original_result()
        run.report["native_seed_verified"]=True
        (run.out/"native-seed.xcresult/Data/result").write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError,"changed before final capture"):run.capture_original_result()

    def folder_fixture(self):
        run,driver=self.seed_fixture()
        run.report.pop("native_folder_verified")
        driver.native_folder_destination=driver.fixture_directory
        driver.native_folder_destination.rmdir()
        driver.fixture_directory=None;driver.fixture_identity=None
        return run,driver

    def test_native_folder_absence_then_empty_adoption_preserves_single_clock_and_environment(self):
        run,driver=self.folder_fixture();calls=[]
        before=driver.deadline;previous=run.commands.ops.env
        def command(label,argv,seconds):
            calls.append((label,[str(a) for a in argv],seconds,dict(run.commands.ops.env)))
            self.assertIsNone(driver.fixture_directory)
            driver.native_folder_destination.mkdir()
        run.command=command
        run.inspect_files_preparation=lambda **kw:self.assertEqual(kw,{"native_folder":True})
        run.prepare_native_folder(driver)
        self.assertEqual(driver.deadline,before);self.assertIs(run.commands.ops.env,previous)
        self.assertEqual(driver.fixture_directory,driver.native_folder_destination)
        self.assertTrue(run.report["native_folder_verified"])
        self.assertTrue(run.report["native_folder"]["empty_after"])
        self.assertEqual(run.report["native_folder"]["leaf_identity"],list(driver.fixture_identity))
        self.assertEqual(len(calls),1)
        label,argv,seconds,env=calls[0]
        self.assertEqual((label,seconds),("native-folder-ui",240))
        self.assertIn("platform=iOS Simulator,id="+OWNED,argv)
        self.assertEqual(argv[argv.index("-maximum-test-execution-time-allowance")+1],"180")
        self.assertEqual([a for a in argv if a.startswith("-only-testing:")],
                         ["-only-testing:TripfolioUITests/"+q.FOLDER_CASE.removesuffix("()")])
        self.assertEqual(env["TEST_RUNNER_TRIPDOCKET_NATIVE_FOLDER_TOKEN"],driver.token)
        self.assertEqual(env["TEST_RUNNER_TRIPDOCKET_BATCH_FOLDER"],driver.folder_name)
        self.assertNotIn("TEST_RUNNER_TRIPDOCKET_NATIVE_SEED_UI",env)
        with self.assertRaises(RuntimeError):run.prepare_native_folder(driver)
        self.assertEqual(len(calls),1)

    def test_native_folder_leaf_rejects_preexisting_link_nonempty_identity_and_bad_token(self):
        for fault in ("existing","link","file","nonempty","provider","token","wrong-name"):
            with tempfile.TemporaryDirectory() as temporary:
                saved=self.root;self.root=Path(temporary).resolve()
                try:run,driver=self.folder_fixture()
                finally:self.root=saved
                target=driver.native_folder_destination
                if fault=="existing":target.mkdir()
                elif fault=="link":target.symlink_to(target.parent,target_is_directory=True)
                elif fault=="file":target.write_bytes(b"not a directory")
                elif fault=="nonempty":target.mkdir();(target/"unexpected").write_bytes(b"retained")
                elif fault=="provider":driver.provider_identity=(0,0)
                elif fault=="token":driver.token=driver.token.upper()
                else:driver.folder_name="wrong"
                with self.subTest(fault=fault),self.assertRaises((RuntimeError,OSError)):
                    run.native_folder_leaf(driver,absent=fault in ("existing","provider","token","wrong-name"))
                self.assertIsNone(driver.fixture_directory)
                if fault=="nonempty":self.assertEqual((target/"unexpected").read_bytes(),b"retained")

    def test_native_folder_provider_replacement_during_empty_scan_is_rejected(self):
        run,driver=self.folder_fixture();target=driver.native_folder_destination;target.mkdir()
        original=q.os.scandir
        def replace(path):
            driver.provider_identity=(0,0)
            return original(path)
        with patch.object(q.os,"scandir",side_effect=replace):
            with self.assertRaisesRegex(RuntimeError,"identity changed"):run.native_folder_leaf(driver)
        self.assertIsNone(driver.fixture_directory)

    def test_native_folder_failed_or_invalid_case_never_adopts_partial_leaf_or_masks_original(self):
        for fault in ("native","inspection","nonempty"):
            with tempfile.TemporaryDirectory() as temporary:
                saved=self.root;self.root=Path(temporary).resolve()
                try:run,driver=self.folder_fixture()
                finally:self.root=saved
                previous=run.commands.ops.env;target=driver.native_folder_destination
                def command(*args):
                    target.mkdir()
                    if fault=="nonempty":(target/"keep").write_bytes(b"keep")
                    if fault=="native":raise RuntimeError("primary native failure")
                def inspect(**kw):
                    if fault in ("native","inspection"):raise RuntimeError("invalid result")
                run.command=command;run.inspect_files_preparation=inspect
                with self.subTest(fault=fault),self.assertRaisesRegex(RuntimeError,
                    "primary native failure" if fault=="native" else "invalid result" if fault=="inspection" else "not empty"):
                    run.prepare_native_folder(driver)
                self.assertIs(run.commands.ops.env,previous);self.assertIsNone(driver.fixture_directory)
                self.assertTrue(target.exists());self.assertFalse(run.report["native_folder"]["adopted"])
                self.assertNotIn("native_folder_verified",run.report)

    def test_failed_root_admission_never_starts_main_or_removes_unowned_path(self):
        run=self.run_object();run.owned=OWNED
        leaf=run.root/"partial-native-folder";leaf.mkdir();(leaf/"keep").write_bytes(b"keep")
        module=SimpleNamespace(timestamp=lambda:"recorded")
        class Driver:
            def __init__(self,args):
                self.directory=run.root/"build/failed-driver";self.directory.mkdir()
                self.summary={};self.fixture_directory=None
                self.actions=(self.directory/"actions.jsonl").open("w")
            def prepare(self):pass
            def run_test(self):raise AssertionError("Main must not run")
            def verify_fixtures(self):raise AssertionError("Unadopted leaf must not be accessed")
            def remove_fixtures(self):raise AssertionError("Unadopted leaf must not be removed")
            def source_snapshot(self):return {"head":HEAD}
            def save(self):(self.directory/"summary.json").write_text(json.dumps(self.summary))
        module.Driver=Driver
        def failed(driver):raise RuntimeError("original root admission failure")
        run.prepare_native_root=failed
        with patch.object(q,"load_module",return_value=module):
            with self.assertRaisesRegex(RuntimeError,"original root admission failure"):run.run_driver()
        self.assertEqual((leaf/"keep").read_bytes(),b"keep")
        summary=json.loads((run.root/run.report["driver_directory"]/"summary.json").read_text())
        self.assertEqual(summary["status"],"failed")
        self.assertIn("owned Simulator teardown only",summary["fixture_cleanup"])
        self.assertEqual(run.driver_calls,0)

    def test_native_folder_admission_requires_full_remaining_original_budget_and_owner(self):
        for fault in ("owner","driver-deadline","outer-deadline","writer","mode","prep","already-exists"):
            with tempfile.TemporaryDirectory() as temporary:
                saved=self.root;self.root=Path(temporary).resolve()
                try:run,driver=self.folder_fixture()
                finally:self.root=saved
                if fault=="owner":run.baseline[OWNED]={}
                elif fault=="driver-deadline":driver.deadline=time.monotonic()+1140
                elif fault=="outer-deadline":run.work_deadline=time.monotonic()+1260
                elif fault=="writer":run.xcode.unknown_spawn=True
                elif fault=="mode":run.mode="biometrics"
                elif fault=="already-exists":driver.native_folder_destination.mkdir()
                else:run.report["files_preparation_verified"]=False
                run.command=lambda *a,**k:self.fail("Native command must not start")
                with self.subTest(fault=fault),self.assertRaises(RuntimeError):run.prepare_native_folder(driver)
                self.assertIsNone(driver.fixture_directory)

    def test_native_folder_result_is_exact_single_case_and_preserves_original(self):
        run=self.run_object();original,summary,tree=self.preparation_fixture(run,native_folder=True)
        before=run.preparation_manifest(original);run.inspect_files_preparation(native_folder=True)
        self.assertEqual(before,run.preparation_manifest(original))
        self.assertEqual(run.report["native_folder_result"]["cases"],[q.FOLDER_CASE])
        with self.assertRaisesRegex(RuntimeError,"Ambiguous"):
            run.inspect_files_preparation(native_seed=True,native_folder=True)
        for fault in ("case","skip","warnings","missing-failures","runtime"):
            result=copy.deepcopy(summary);nodes=copy.deepcopy(tree)
            if fault=="case":nodes["testNodes"][0]["nodeIdentifier"]=q.SEED_CASE
            elif fault=="skip":result.update(skippedTests=1,passedTests=0)
            elif fault=="warnings":result["runtimeWarnings"]=[{}]
            elif fault=="missing-failures":result.pop("testFailures")
            else:result["devicesAndConfigurations"][0]["device"]["osVersion"]="18.5"
            with self.subTest(fault=fault),self.assertRaises(RuntimeError):
                q.validate_files_preparation(result,nodes,OWNED,run.report["runtime_selection"],q.FOLDER_CASE)

    def test_final_capture_requires_native_folder_and_rechecks_original_after_cleanup(self):
        run,_=self.prepared_capture();run.report["cleanup_verified"]=True
        run.report.pop("native_folder_verified")
        with self.assertRaisesRegex(RuntimeError,"Missing verified"):run.capture_original_result()
        run.report["native_folder_verified"]=True
        (run.out/"native-folder.xcresult/Data/result").write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError,"changed before final capture"):run.capture_original_result()

    def test_workflow_is_explicit_read_only_and_uses_original_drivers(self):
        workflow=(Path(__file__).parent.parent/".github/workflows/release-qualification.yml").read_text()
        self.assertIn("workflow_dispatch:",workflow);self.assertIn("contents: read",workflow)
        self.assertNotIn("contents: write",workflow);self.assertNotIn("pull_request_target",workflow)
        self.assertIn("persist-credentials: false",workflow)
        self.assertIn("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",workflow)
        self.assertIn("actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9",workflow)
        self.assertEqual(set(q.MODES),{"batch","biometrics"})
        self.assertIn("DEVELOPER_DIR: " + q.DEVELOPER_DIR, workflow)
        self.assertIn('run-name: "Release qualification: ${{ inputs.mode }}"', workflow)
        self.assertIn("python3 -B scripts/test-batch-scroll-container.py", workflow)
        ci=(Path(__file__).parent.parent/".github/workflows/ci.yml").read_text()
        self.assertIn('--validate-schemas', ci)
        self.assertIn('summary --schema >', ci)
        self.assertIn('tests --schema >', ci)
        self.assertNotIn('--schema-version', ci)
        self.assertNotIn('export DEVELOPER_DIR=', ci)



class SharedBuildGuards(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.run=q.Qualification(self.root,"batch",ENV)
        self.run.owned=OWNED;self.run.baseline={}
        self.derived=self.root/"build/QualificationPreparationDerivedData-123-1"
        products=self.derived/"Build/Products/Debug-iphonesimulator";products.mkdir(parents=True)
        app=products/"Tripfolio.app";host=app/"PlugIns/TripfolioTests.xctest"
        ui=products/"TripfolioUITests-Runner.app/PlugIns/TripfolioUITests.xctest"
        self.paths={"Tripfolio":app,"TripfolioTests":host,"TripfolioUITests":ui}
        ids={"Tripfolio":q.APP_ID,"TripfolioTests":q.APP_ID+".tests","TripfolioUITests":q.APP_ID+".uitests"}
        self.settings=[]
        for target,path in self.paths.items():
            path.mkdir(parents=True,exist_ok=True)
            (path/"Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier":ids[target]}))
            (path/target).write_bytes(target.encode())
            self.settings.append({"target":target,"buildSettings":{"CONFIGURATION":"Debug",
                "PLATFORM_NAME":"iphonesimulator","PRODUCT_BUNDLE_IDENTIFIER":ids[target],
                "SYMROOT":str(products.parent),"BUILT_PRODUCTS_DIR":str(products),
                "TARGET_BUILD_DIR":str(path.parent),"FULL_PRODUCT_NAME":path.name}})
        runner=ui.parent.parent
        (runner/"Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier":q.RUNNER_ID}))
        frameworks=runner/"Frameworks";frameworks.mkdir()
        (frameworks/"runtime.dylib").write_bytes(b"runtime")
        self.paths["TripfolioUITestsRunner"]=runner
        self.run.report.update(files_preparation_verified=True,
            files_preparation={"derived_data":str(self.derived.relative_to(self.root))})
        self.driver=SimpleNamespace(args=SimpleNamespace(native_root=True),remaining=lambda:1200,summary={})
        self.calls=[]
        data=self.root/"data";data.mkdir()
        def command(label,argv,seconds=30):
            self.calls.append((label,argv,seconds))
            if label=="shared-build-settings":return json.dumps(self.settings)
            return str(data if argv[-1]=="data" else app)
        self.run.command=command
        self.run.container_path=lambda value,*kind:Path(value)

    def test_actual_paths_and_three_observations_keep_products_bytes_modes_and_clock(self):
        self.run.prepare_shared_build(self.driver)
        self.assertEqual(self.run.shared_products,self.paths)
        self.assertEqual(self.driver.qualified_build,self.derived)
        self.run.observe_shared_build(self.driver,"after_seed")
        self.run.observe_shared_build(self.driver,"after_main")
        proof=self.run.report["shared_build"]
        self.assertEqual(set(proof["observations"]),{"before_seed","after_seed","after_main"})
        self.assertEqual(len(self.calls),7);self.assertTrue(all(c[2]==30 for c in self.calls))
        self.assertIn("-showBuildSettings",self.calls[0][1])
        self.assertEqual(self.calls[0][1][-1],"build-for-testing")
        for ref in proof["observations"].values():
            raw=(self.run.out/ref["path"]).read_bytes();self.assertEqual(hashlib.sha256(raw).hexdigest(),ref["sha256"])
            value=json.loads(raw);self.assertEqual(set(value["products"]),set(self.paths))
            self.assertIn("modes",value["products"]["Tripfolio"])
            self.assertIn("identity",value["installed"]["data"])
        with self.assertRaises(RuntimeError):self.run.observe_shared_build(self.driver,"after_main")

    def test_missing_duplicate_wrong_platform_identity_or_escaped_target_fails(self):
        variants=[self.settings[:-1],self.settings+[self.settings[0]]]
        for key,value in [("CONFIGURATION","Release"),("PLATFORM_NAME","iphoneos"),
                          ("PRODUCT_BUNDLE_IDENTIFIER","wrong"),("TARGET_BUILD_DIR",str(self.root)),
                          ("FULL_PRODUCT_NAME","../outside")]:
            variant=copy.deepcopy(self.settings);variant[0]["buildSettings"][key]=value;variants.append(variant)
        for value in variants:
            with self.subTest(value=value),self.assertRaises(RuntimeError):
                q.shared_product_paths(json.dumps(value),self.derived)
        with self.assertRaises(RuntimeError):q.shared_product_paths(" "*(q.MIB+1),self.derived)
        (self.paths["TripfolioTests"]/"Info.plist").unlink()
        with self.assertRaises((RuntimeError,OSError)):q.shared_product_paths(json.dumps(self.settings),self.derived)

    def test_changed_bytes_or_modes_and_replaced_derived_directory_rejected(self):
        self.run.prepare_shared_build(self.driver)
        p=self.paths["Tripfolio"]/"Tripfolio";original=p.read_bytes();mode=p.stat().st_mode
        p.write_bytes(b"different")
        with self.assertRaisesRegex(RuntimeError,"products changed"):self.run.observe_shared_build(self.driver,"after_seed")
        p.write_bytes(original);p.chmod(0o700)
        with self.assertRaisesRegex(RuntimeError,"products changed"):self.run.observe_shared_build(self.driver,"after_seed")
        p.chmod(mode)
        self.run.shared_derived_identity=(0,0)
        with self.assertRaisesRegex(RuntimeError,"identity changed"):self.run.observe_shared_build(self.driver,"after_seed")

    def test_symlink_product_or_inactive_budget_never_starts_seed(self):
        p=self.paths["TripfolioTests"];moved=p.with_name("Original.xctest");p.rename(moved);p.symlink_to(moved)
        with self.assertRaises((RuntimeError,OSError)):q.shared_product_paths(json.dumps(self.settings),self.derived)
        self.driver.remaining=lambda:1174
        with self.assertRaisesRegex(RuntimeError,"budget"):self.run.prepare_shared_build(self.driver)
        self.assertEqual(self.calls,[])
        self.driver.remaining=lambda:1200;self.run.commands.active[999]=object()
        with self.assertRaisesRegex(RuntimeError,"writer"):self.run.prepare_shared_build(self.driver)
        self.assertEqual(self.calls,[])

    def test_installed_bytes_mismatch_and_expired_postcheck_fail(self):
        self.run.prepare_shared_build(self.driver)
        other=self.root/"different-app";other.mkdir();(other/"Info.plist").write_bytes(b"bad")
        self.run.command=lambda *args:str(other)
        with self.assertRaisesRegex(RuntimeError,"Installed app differs"):self.run.observe_shared_build(self.driver,"after_seed")
        self.driver.remaining=lambda:0
        with self.assertRaisesRegex(RuntimeError,"deadline"):self.run.observe_shared_build(self.driver,"after_seed")

    def test_shared_command_preserves_stop_reserve_inside_driver_deadline(self):
        self.driver.remaining=lambda:19
        self.run.shared_build_command(self.driver,"observation",["query"])
        self.assertEqual(self.calls[-1][2],11)
        self.driver.remaining=lambda:8
        with self.assertRaisesRegex(RuntimeError,"budget"):
            self.run.shared_build_command(self.driver,"observation",["query"])

    def test_shared_settings_require_same_symroot_and_real_bundle_identifier(self):
        different=self.derived/"other";different.mkdir()
        bad=copy.deepcopy(self.settings);bad[1]["buildSettings"]["SYMROOT"]=str(different)
        with self.assertRaisesRegex(RuntimeError,"SYMROOT"):
            q.shared_product_paths(json.dumps(bad),self.derived)
        (self.paths["Tripfolio"]/"Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier":"other"}))
        with self.assertRaisesRegex(RuntimeError,"plist identity"):
            q.shared_product_paths(json.dumps(self.settings),self.derived)

    def test_products_uses_shared_built_paths_instead_of_driver_default(self):
        self.run.prepare_shared_build(self.driver)
        runner=self.paths["TripfolioUITests"].parent.parent
        (runner/"Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier":q.RUNNER_ID}))
        self.run.command=lambda label,argv,seconds:str(runner if argv[-2]==q.RUNNER_ID else self.paths["Tripfolio"])
        self.driver.directory=self.root/"nonexistent-default"
        self.run.products(self.driver)
        self.assertTrue(self.run.report["products_verified"])

    def test_runner_frameworks_are_included_in_compiled_product_identity(self):
        self.run.prepare_shared_build(self.driver)
        (self.paths["TripfolioUITestsRunner"]/"Frameworks/runtime.dylib").write_bytes(b"changed runtime")
        with self.assertRaisesRegex(RuntimeError,"products changed"):
            self.run.observe_shared_build(self.driver,"after_seed")

if __name__ == "__main__":
    unittest.main(verbosity=2)
