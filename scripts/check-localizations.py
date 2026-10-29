#!/usr/bin/env python3
"""Validate shipped localization resources and statically referenced app keys."""
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = {"en", "ru"}


def leaves(value):
    if isinstance(value, dict):
        if "stringUnit" in value:
            yield value["stringUnit"]
        for item in value.values():
            yield from leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from leaves(item)


def check_plural(value, language, context):
    if not isinstance(value, dict):
        return
    plural = value.get("variations", {}).get("plural")
    if plural is not None:
        required = {"one", "other"} if language == "en" else {"one", "few", "many", "other"}
        assert required <= set(plural), f"Missing plural variants: {context}"
    for item in value.values():
        if isinstance(item, dict):
            check_plural(item, language, context)


def strings(path):
    return json.loads(subprocess.check_output(
        ["plutil", "-convert", "json", "-o", "-", str(path)], text=True))


def main():
    source = "\n".join(p.read_text() for p in (ROOT / "App").glob("*.swift"))
    counts = {}
    with tempfile.TemporaryDirectory(prefix="tripdocket-l10n-") as output:
        for table, function in [("UI", "ui"), ("Services", "service")]:
            path = ROOT / "App" / f"{table}.xcstrings"
            catalog = json.loads(path.read_text())
            assert catalog["sourceLanguage"] == "en"
            entries = catalog["strings"]
            referenced = set(re.findall(rf'L10n\.{function}\(\s*"([^"]+)"', source))
            assert referenced <= set(entries), f"Missing {table} keys: {referenced - set(entries)}"
            assert set(entries) <= referenced, f"Unreferenced {table} keys: {set(entries) - referenced}"
            for key, entry in entries.items():
                assert set(entry["localizations"]) == LANGUAGES, f"Languages differ: {table}.{key}"
                for language, value in entry["localizations"].items():
                    units = list(leaves(value))
                    assert units, f"No translations: {table}.{key}.{language}"
                    assert all(u.get("state") == "translated" and u.get("value") for u in units), key
                    check_plural(value, language, f"{table}.{key}.{language}")
            subprocess.run(["xcrun", "xcstringstool", "compile", str(path),
                            "--output-directory", output], check=True)
            counts[table] = len(entries)

    for base, name in [(ROOT / "App", "InfoPlist"), (ROOT / "App", "Localizable"),
                       (ROOT / "Sources/TravelCore/Resources", "Core")]:
        translations = {lang: strings(base / f"{lang}.lproj" / f"{name}.strings") for lang in LANGUAGES}
        keys = set(translations["en"])
        assert keys == set(translations["ru"]), f"Mismatched {name} keys"
        assert all(isinstance(text, str) and text for values in translations.values() for text in values.values())
        counts[name] = len(keys)
        if name == "Localizable":
            notifications = set(re.findall(r'localizedUserNotificationString\(forKey:\s*"([^"]+)"', source))
            assert notifications == keys, f"Notification keys differ: {notifications ^ keys}"

    print("Localization catalogs, app key coverage, plural variants and resources passed: " + json.dumps(counts))


if __name__ == "__main__":
    main()
