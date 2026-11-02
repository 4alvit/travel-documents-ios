#!/usr/bin/env python3
"""Select an existing SDK-matched iPhone from captured inventories; never mutate it."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import uuid


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identifier(value):
    require(isinstance(value, str), "Device UUID must be a string")
    return str(uuid.UUID(value)).upper()


def select_device(sdk, architecture, runtimes, device_types, devices, requested=None):
    require(isinstance(sdk, str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", sdk), "Invalid SDK version")
    require(tuple(map(int, sdk.split("."))) >= (17,), "SDK predates the app minimum")
    require(architecture in {"arm64", "x86_64"}, "Unsupported host architecture")
    rows = runtimes["runtimes"]
    require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows), "Invalid runtime inventory")
    matches = [row for row in rows if row.get("version") == sdk
               and row.get("identifier", "").startswith("com.apple.CoreSimulator.SimRuntime.iOS-")]
    require(len(matches) == 1, "No unique exact SDK-matched runtime")
    runtime = matches[0]
    require(sum(row.get("identifier") == runtime["identifier"] for row in rows) == 1,
            "Ambiguous selected runtime identifier")
    require(runtime.get("isAvailable") is True, "SDK-matched runtime unavailable")
    require(isinstance(runtime.get("supportedArchitectures"), list)
            and architecture in runtime["supportedArchitectures"], "Runtime does not support host architecture")
    require(isinstance(runtime.get("buildversion"), str) and runtime["buildversion"], "Runtime build identity missing")
    types = device_types["devicetypes"]
    require(isinstance(types, list) and all(isinstance(row, dict) for row in types), "Invalid device type inventory")
    type_map = {row["identifier"]: row for row in types}
    require(len(type_map) == len(types), "Duplicate device type identifier")
    supported = runtime.get("supportedDeviceTypes")
    require(isinstance(supported, list) and all(isinstance(row, dict) for row in supported), "Missing runtime device compatibility")
    supported_ids = [row["identifier"] for row in supported]
    require(len(supported_ids) == len(set(supported_ids)), "Duplicate runtime device compatibility")
    phones = {key for key in supported_ids if key in type_map and type_map[key].get("productFamily") == "iPhone"
              and key.startswith("com.apple.CoreSimulator.SimDeviceType.iPhone-")}
    require(phones, "Runtime has no explicitly compatible iPhone")
    inventory = devices["devices"]
    require(isinstance(inventory, dict), "Invalid device inventory")
    all_devices, candidates = {}, []
    for runtime_id, entries in inventory.items():
        require(isinstance(entries, list), "Invalid runtime device list")
        for device in entries:
            require(isinstance(device, dict), "Invalid device entry")
            udid = identifier(device["udid"])
            require(udid not in all_devices, "Duplicate device UUID")
            all_devices[udid] = device
            if runtime_id == runtime["identifier"] and device.get("isAvailable") is True \
                    and device.get("deviceTypeIdentifier") in phones:
                require(isinstance(device.get("name"), str) and device["name"], "Device name missing")
                candidates.append((udid, device))
    require(candidates, "No available compatible iPhone in the SDK-matched runtime")
    if requested is not None:
        wanted = identifier(requested)
        candidates = [row for row in candidates if row[0] == wanted]
        require(len(candidates) == 1, "Requested UUID is not an available SDK/architecture-compatible iPhone")
    # Retain the existing inventory order within the selected runtime, avoiding
    # a gratuitous device-model change when that runtime was already selected.
    udid, device = candidates[0]
    return {"selection": "exact-sdk-host-architecture", "sdk": sdk, "architecture": architecture,
            "runtime": runtime["identifier"], "runtime_build": runtime["buildversion"],
            "udid": udid, "device_type": device["deviceTypeIdentifier"], "device_name": device["name"],
            "requested_udid": identifier(requested) if requested is not None else None}


def read_file(path):
    require(path.is_file() and not path.is_symlink(), "Inventory must be a regular file")
    with path.open("rb") as stream:
        data = stream.read(8 * 1024 * 1024 + 1)
    require(0 < len(data) <= 8 * 1024 * 1024, "Inventory size limit exceeded")
    return data


def decode(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--requested-udid")
    args = parser.parse_args()
    try:
        directory = args.inventory.absolute()
        require(directory.is_dir() and directory.resolve(strict=True) == directory,
                "Inventory directory must not contain symbolic links or traversal")
        names = ["sdk.txt", "architecture.txt", "runtimes.json", "device-types.json", "devices.json"]
        raw = {name: read_file(directory / name) for name in names}
        result = select_device(raw["sdk.txt"].decode().strip(), raw["architecture.txt"].decode().strip(),
                               decode(raw["runtimes.json"]), decode(raw["device-types.json"]),
                               decode(raw["devices.json"]), args.requested_udid)
        result["inventory_sha256"] = {name: hashlib.sha256(data).hexdigest() for name, data in raw.items()}
        with (directory / "selection.json").open("x") as stream:
            json.dump(result, stream, indent=2); stream.write("\n")
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        parser.exit(1, "Simulator selection failed: " + str(error) + "\n")
    print(result["udid"])


if __name__ == "__main__":
    main()
