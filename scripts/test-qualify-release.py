#!/usr/bin/env python3
"""Offline guards for the explicit hosted qualification adapter."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("qualification", Path(__file__).with_name("qualify-release.py"))
q = importlib.util.module_from_spec(spec); spec.loader.exec_module(q)
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
        cases = ["Batch/case()"] if mode == "batch" else ["Privacy/case" + str(n) + "()" for n in range(6)]
        source = {"head": HEAD, "status": "", "dirty": False}
        summary = {"status": "passed", "device": OWNED, "xcodebuild_returncode": 0,
                   "source_before": source, "source_after": copy.deepcopy(source),
                   "source_originals_unchanged": True, "fixture_cleanup": "removed only the uniquely created fixture folder",
                   "selected_method": None, "requests": {"match": 4, "nomatch": 1}}
        result = {"result": "Passed", "totalTestCount": len(cases), "passedTests": len(cases),
                  "failedTests": 0, "skippedTests": 0, "expectedFailures": 0,
                  "runtimeWarnings": [], "testFailures": [],
                  "devicesAndConfigurations": [{"device": {"deviceId": OWNED}}]}
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

    def test_runtime_is_exact_sdk_architecture_and_available(self):
        runtime = {"version": "18.5", "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-18-5",
                   "isAvailable": True, "supportedArchitectures": ["arm64"],
                   "supportedDeviceTypes": [{"identifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro"}]}
        self.assertEqual(q.choose_runtime({"runtimes": [runtime]}, "18.5", "arm64")[0], runtime["identifier"])
        for values, sdk, arch in [([runtime], "27.0", "arm64"), ([runtime], "18.5", "x86_64"),
                                  ([runtime, runtime], "18.5", "arm64"),
                                  ([{**runtime, "isAvailable": False}], "18.5", "arm64"),
                                  ([{**runtime, "supportedDeviceTypes": []}], "18.5", "arm64")]:
            with self.assertRaises(RuntimeError): q.choose_runtime({"runtimes": values}, sdk, arch)

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

    def exercise_driver(self, *, skipped=False, runtime_warning=False, missing_warnings=False):
        run=self.run_object();run.owned=OWNED
        summary,result,tree,cases=self.fixture()
        if skipped:result.update(passedTests=0,skippedTests=1)
        if runtime_warning:result["runtimeWarnings"]=[{"message":"Runtime issue"}]
        if missing_warnings:result.pop("runtimeWarnings")
        source=summary["source_before"]
        child=SimpleNamespace(pid=123,returncode=0,stdout=None,stderr=None,poll=lambda:0)
        events=[]
        module=SimpleNamespace(CASE=cases[0],timestamp=lambda:"recorded")
        class Driver:
            def __init__(self,args):
                self.directory=run.root/"build/BatchSimulator-fixture";self.directory.mkdir()
                self.summary=copy.deepcopy(summary);self.actions=(self.directory/"actions.jsonl").open("w")
            def prepare(self):events.append("prepare")
            def run_test(self):
                events.append("test")
                module.subprocess.Popen(["xcodebuild","-destination","platform=iOS Simulator,id="+OWNED],
                                        cwd=run.root,start_new_session=True)
                (self.directory/"xcresult-summary.json").write_text(json.dumps(result))
                (self.directory/"xcresult-tests.json").write_text(json.dumps(tree))
            def verify_fixtures(self):events.append("verify-fixtures")
            def remove_fixtures(self):events.append("remove-fixtures")
            def source_snapshot(self):return copy.deepcopy(source)
            def save(self):(self.directory/"summary.json").write_text(json.dumps(self.summary))
        module.Driver=Driver
        run.xcode.ops=SimpleNamespace(now=time.monotonic,absent=lambda p:True,
                                     send=lambda *_:self.fail("Completed process needs no signal"))
        run.products=lambda driver:events.append("products")
        run.batch_snapshot=lambda driver:events.append("batch-snapshot")
        with patch.object(q,"load_module",return_value=module),patch.object(q.subprocess,"Popen",return_value=child):
            if skipped or runtime_warning:
                with self.assertRaises(RuntimeError):run.run_driver()
            else:run.run_driver()
        self.assertFalse(run.xcode.active)
        stop=run.xcode.report["commands"][0]["stop"]
        self.assertTrue(stop["group_absent"]);self.assertTrue(stop["leader_reaped"])
        self.assertEqual(events.count("test"),1)
        return run,events

    def test_original_driver_adapter_finishes_one_owned_process_before_product_acceptance(self):
        run,events=self.exercise_driver()
        self.assertEqual(events,["prepare","test","verify-fixtures","remove-fixtures","products","batch-snapshot"])
        self.assertTrue(run.report["driver_capture_verified"])

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
        return run,result

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

    def test_batch_preflight_pins_observed_reader_without_claiming_schema_support(self):
        raw = (Path(__file__).parent / "fixtures/xcresult-xcode-16.4/xcresulttool-version.txt").read_bytes()
        run = self.run_object(); calls = []
        run.command = lambda label, argv, seconds=30: calls.append(argv) or raw.decode()
        run.preflight_schemas()
        self.assertEqual(calls, [["xcrun", "xcresulttool", "version"]])
        report = run.report["xcresult_schema"]
        self.assertEqual(report["status"], "unsupported_by_producer")
        self.assertEqual(report["xcresulttool_version"], q.toolchain_profile("batch")["xcresulttool_version"])
        self.assertEqual((run.out / report["version_file"]).read_bytes(), raw)
        self.assertEqual(report["version_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertNotIn("documentation_verified", report)
        self.assertIn("Independent pinned-reader review", report["runtime_evidence"])
        self.assertFalse(list(run.out.glob("xcresult-schema-*")))
        self.assertIsNone(run.owned)
        with self.assertRaisesRegex(RuntimeError, "does not support"):
            q.validate_schemas(*self.schemas(), mode="batch")

    def test_batch_preflight_rejects_unknown_reader_before_device_actions(self):
        run = self.run_object()
        for raw in ["", "xcresulttool version 23715, format version 3.53 (current)",
                    "xcresulttool version 23714, format version 3.54 (current)", "Xcode 16.4"]:
            run.command = lambda *args: raw
            with self.subTest(raw=raw), self.assertRaisesRegex(RuntimeError, "xcresulttool"):
                run.preflight_schemas()
            self.assertNotIn("xcresult_schema", run.report)
            self.assertIsNone(run.owned)

    def test_mode_profiles_reject_wrong_xcode_sdk_or_environment_before_native_work(self):
        for mode in q.MODES:
            profile = q.toolchain_profile(mode)
            other = q.toolchain_profile("biometrics" if mode == "batch" else "batch")
            for key, value in [("xcode", other["xcode_version"]), ("sdk", other["sdk_version"]),
                               ("environment", other["developer_dir"])]:
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
        self.assertEqual((batch["xcode_version"], batch["sdk_version"]), ("Xcode 16.4\nBuild version 16F6", "18.5"))
        self.assertIsNone(batch["schema_documents"])
        self.assertEqual((bio["xcode_version"], bio["developer_dir"]), (q.XCODE_VERSION, q.DEVELOPER_DIR))
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
            self.assertEqual("xcresulttool-version" in calls, mode == "batch")
            self.assertEqual("xcresult-schema-summary" in calls, mode == "biometrics")
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
                with self.assertRaisesRegex(RuntimeError, "does not support"): q.main()
            with patch.object(q.sys, "argv", ["qualify-release.py", "--mode", "batch", "--schema-mode", "biometrics"]):
                with self.assertRaises(SystemExit): q.main()
        link = self.root / "link"; link.symlink_to(paths[0])
        with patch.object(q.sys, "argv", ["qualify-release.py", "--validate-schemas", str(link), paths[1]]):
            with self.assertRaises(RuntimeError): q.main()

    def test_workflow_is_explicit_read_only_and_uses_original_drivers(self):
        workflow=(Path(__file__).parent.parent/".github/workflows/release-qualification.yml").read_text()
        self.assertIn("workflow_dispatch:",workflow);self.assertIn("contents: read",workflow)
        self.assertNotIn("contents: write",workflow);self.assertNotIn("pull_request_target",workflow)
        self.assertIn("persist-credentials: false",workflow)
        self.assertIn("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",workflow)
        self.assertIn("actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9",workflow)
        self.assertEqual(set(q.MODES),{"batch","biometrics"})
        self.assertIn("DEVELOPER_DIR: ${{ inputs.mode == 'batch' && '" + q.toolchain_profile("batch")["developer_dir"]
                      + "' || '" + q.DEVELOPER_DIR + "' }}", workflow)
        ci=(Path(__file__).parent.parent/".github/workflows/ci.yml").read_text()
        self.assertIn('--validate-schemas', ci)
        self.assertIn('summary --schema >', ci)
        self.assertIn('tests --schema >', ci)
        self.assertNotIn('--schema-version', ci)
        self.assertNotIn('export DEVELOPER_DIR=', ci)


if __name__ == "__main__":
    unittest.main(verbosity=2)
