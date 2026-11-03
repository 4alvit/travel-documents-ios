#!/usr/bin/env python3
"""Diagnostic-only Xcode 26.2 batch run on the exact iOS 18.5 Simulator."""
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import stat
import sys

HERE = Path(__file__).resolve().parent
PROVIDER_SHA256 = "49c90b8aff5eb6aa2bb24e1e9a75e09e2469c3429c0978f7841551fd08d277db"
RUNTIME = "com.apple.CoreSimulator.SimRuntime.iOS-18-5"
RUNTIME_VERSION = "18.5"
RUNTIME_BUILD = "22F77"
DEVICE_TYPE = "com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro"
PRODUCTS = {"Tripfolio", "TripfolioTests", "TripfolioUITests", "TripfolioUITestsRunner"}


def verify_provider():
    path = HERE / "diagnose-batch-provider.py"
    metadata = path.lstat()
    if (not stat.S_ISREG(metadata.st_mode) or path.resolve() != path
            or metadata.st_size > 2 * 1024**2
            or hashlib.sha256(path.read_bytes()).hexdigest() != PROVIDER_SHA256):
        raise RuntimeError("Runtime diagnostic provider helper changed")


verify_provider()
spec = importlib.util.spec_from_file_location("runtime_diagnostic_provider", HERE / "diagnose-batch-provider.py")
provider = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider)
verify_provider()
q = provider.q
BASE_PROFILE = q.toolchain_profile
BASE_CHOOSER = q.choose_runtime


def runtime_profile(mode):
    q.require(mode == "batch", "Runtime control is batch-only")
    # Preserve the pinned developer directory, SDK, Xcode and result schemas.
    return {**BASE_PROFILE(mode), "runtime_version": RUNTIME_VERSION}


def choose_runtime(data, version, architecture):
    q.require(version == RUNTIME_VERSION and architecture == "arm64",
              "Runtime control requires iOS 18.5 on ARM64")
    selected, device = BASE_CHOOSER(data, version, architecture)
    q.require(selected == RUNTIME and device == DEVICE_TYPE,
              "Runtime control requires exact iOS 18.5 and iPhone 16 Pro; no fallback")
    records = [row for row in data["runtimes"] if row.get("identifier") == RUNTIME]
    q.require(len(records) == 1 and records[0].get("version") == RUNTIME_VERSION
              and records[0].get("buildversion") == RUNTIME_BUILD
              and records[0].get("isAvailable") is True
              and "arm64" in records[0].get("supportedArchitectures", []),
              "Runtime control requires available iOS 18.5 build 22F77 for ARM64")
    return selected, device


def product_compatibility(raw):
    info = q.plistlib.loads(raw)
    q.require(isinstance(info, dict), "Invalid compiled product plist")
    minimum = info.get("MinimumOSVersion")
    q.require(isinstance(minimum, str)
              and re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,3}){1,2}", minimum),
              "Missing or invalid compiled MinimumOSVersion")
    parts = tuple(int(part) for part in minimum.split("."))
    q.require(parts + (0,) * (3 - len(parts)) <= (18, 5, 0),
              "Compiled product requires a newer runtime than iOS 18.5")
    q.require(info.get("CFBundleSupportedPlatforms") == ["iPhoneSimulator"]
              and info.get("DTPlatformName") == "iphonesimulator",
              "Compiled product is not for the iOS Simulator")
    return {"minimum_os_version": minimum, "platform": info["DTPlatformName"],
            "supported_platforms": info["CFBundleSupportedPlatforms"],
            "info_plist_sha256": hashlib.sha256(raw).hexdigest(), "info_plist_bytes": len(raw)}


class RuntimeQualification(provider.ProviderLogQualification):
    def __init__(self, root, mode, env):
        q.require(mode == "batch" and env.get("QUALIFICATION_RUNTIME_CONTROL") == "ios18.5",
                  "Select the explicit ios18.5 batch runtime control")
        q.require(q.toolchain_profile is runtime_profile and q.choose_runtime is choose_runtime,
                  "Runtime control hooks are not installed")
        # The inherited constructor rejects non-ARM, unofficial workflow context
        # and optional reopen before any output directory or device allocation.
        super().__init__(root, mode, env)

    def save(self):
        diagnostic = self.report.setdefault("diagnostic_runtime_control", {
            "control": "ios18.5", "release_acceptance": False, "sdk_matched": False,
            "scope": "Xcode/SDK 26.2 on iOS 18.5; supporting diagnostic, not release qualification",
            "sdk_version": "26.2", "runtime_version": RUNTIME_VERSION,
            "runtime_identifier": RUNTIME, "runtime_build": RUNTIME_BUILD,
            "architecture": "arm64", "device_type": DEVICE_TYPE,
            "provider_sha256": PROVIDER_SHA256, "product_compatibility": {"status": "pending"},
        })
        if (self.report.get("status") == "captured_pending_review"
                and diagnostic["product_compatibility"].get("status") != "verified"):
            self.report["status"] = "diagnostic_incomplete"
        super().save()

    def prepare_shared_build(self, driver):
        # Retain every actual path, full-product identity and installed-byte
        # check; validate compatibility before the inherited caller starts seed.
        super().prepare_shared_build(driver)
        self.require_no_build_writer()

        def check():
            self.check()
            q.require(driver.remaining() > 0, "Runtime product check exceeded driver deadline")

        check()
        q.require(set(self.shared_products) == PRODUCTS, "Missing compiled runtime-control products")
        records = {}
        for name, path in self.shared_products.items():
            raw = q.bounded_read(path, "Info.plist", q.MIB, check)
            record = product_compatibility(raw)
            q.require(self.shared_product_identity[name]["content"]["./Info.plist"]
                      == {"kind": "file", "bytes": len(raw), "sha256": record["info_plist_sha256"]},
                      "Compiled product plist changed after shared identity verification")
            records[name] = record
        check()
        self.report["diagnostic_runtime_control"]["product_compatibility"] = {
            "status": "verified", "before_phase": "seed", "products": records}
        self.save()


def main():
    q.require(sys.argv[1:] == ["--mode", "batch"], "Runtime diagnostic requires --mode batch")
    q.require(os.environ.get("QUALIFICATION_RUNTIME_CONTROL") == "ios18.5",
              "Select the explicit ios18.5 batch runtime control")
    verify_provider()
    provider.verify_pins(HERE)
    previous = q.Qualification, q.toolchain_profile, q.choose_runtime
    q.require(previous == (provider.BaseQualification, BASE_PROFILE, BASE_CHOOSER),
              "Runtime diagnostic inherited hooks changed")
    q.Qualification, q.toolchain_profile, q.choose_runtime = RuntimeQualification, runtime_profile, choose_runtime
    try:
        # Preserve the original signal handlers and all native/process clocks.
        return q.main()
    finally:
        q.Qualification, q.toolchain_profile, q.choose_runtime = previous


if __name__ == "__main__":
    sys.exit(main())
