#!/usr/bin/env python3
"""Exercise actual List-wrapper and count-row helpers without native UI calls."""
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "UITests/BatchImportUITests.swift"

MODEL = r'''
import Foundation
import CoreGraphics
@MainActor final class XCUIElementQuery {
    var allElementsBoundByIndex: [XCUIElement] = []
    var count: Int { allElementsBoundByIndex.count }
    var firstMatch: XCUIElement { allElementsBoundByIndex[0] }
    func element(boundBy index: Int) -> XCUIElement { allElementsBoundByIndex[index] }
}
@MainActor struct RowSnapshot {
    let identifier: String
    let label: String
    let value: Any?
}
@MainActor final class XCUIElement {
    var exists = true
    var isHittable = false
    var frame: CGRect
    var identifier = "settings.count.trips"
    var label = "Trips"
    var value: Any? = "1"
    var snapshotFails = false
    let buttons = XCUIElementQuery()
    let staticTexts = XCUIElementQuery()
    func snapshot() throws -> RowSnapshot {
        if snapshotFails { throw SnapshotFailure() }
        return RowSnapshot(identifier: identifier, label: label, value: value)
    }
    struct SnapshotFailure: Error {}
    init(_ frame: CGRect, hittable: Bool = false) {
        self.frame = frame; self.isHittable = hittable
    }
}
'''

CASES = r'''
@main struct GuardRunner {
    @MainActor static func main() {
        let h = Harness()
        var passed = 0
        func check(_ value: Bool, _ message: String) {
            guard value else { print("FAIL " + message); exit(1) }
            passed += 1
        }
        let nav = CGRect(x: 0, y: 62, width: 402, height: 106)
        let viewport = CGRect(x: 6, y: 176, width: 390, height: 607)
        let full = CGRect(x: 0, y: 0, width: 402, height: 874)
        func wrapper() -> XCUIElement {
            let item = XCUIElement(full)
            item.buttons.allElementsBoundByIndex = [
                XCUIElement(CGRect(x: 16, y: 255, width: 370, height: 109), hittable: true)
            ]
            return item
        }
        func select(_ items: [XCUIElement]) -> XCUIElement? {
            h.revealContainer(items, navigationFrame: nav, viewport: viewport)
        }
        let good = wrapper()
        check(select([good]) === good, "visible native List wrapper with live child")
        let textOnly = wrapper()
        textOnly.staticTexts.allElementsBoundByIndex = textOnly.buttons.allElementsBoundByIndex
        textOnly.buttons.allElementsBoundByIndex = []
        check(select([textOnly]) === textOnly, "visible static text proves wrapper")
        let direct = XCUIElement(full, hittable: true)
        check(select([direct, good, wrapper()]) === direct, "direct path precedes ambiguous wrappers")
        let secondDirect = XCUIElement(full, hittable: true)
        check(select([direct, secondDirect]) === secondDirect, "original reverse direct order")
        check(select([wrapper(), wrapper()]) == nil, "two live geometric wrappers rejected")
        let covered = wrapper(); covered.buttons.allElementsBoundByIndex[0].isHittable = false
        let foreground = wrapper()
        check(select([foreground, covered]) === foreground, "one live wrapper survives a covered geometric match")
        check(select([covered, foreground]) === foreground, "covered match does not make selection order-dependent")
        check(select([foreground, XCUIElement(full)]) === foreground, "empty geometric match does not hide the live wrapper")
        let coveredToo = wrapper(); coveredToo.buttons.allElementsBoundByIndex[0].isHittable = false
        check(select([covered, coveredToo]) == nil, "two covered wrappers are not active")
        let offscreen = wrapper(); offscreen.buttons.allElementsBoundByIndex[0].frame.origin.y = 900
        check(select([offscreen, foreground]) === foreground, "offscreen live child does not create active ambiguity")
        let absentChild = wrapper(); absentChild.buttons.allElementsBoundByIndex[0].exists = false
        check(select([absentChild, foreground]) === foreground, "missing child does not create active ambiguity")
        covered.buttons.allElementsBoundByIndex[0].isHittable = true
        check(select([covered, foreground]) == nil, "newly active second wrapper rejects on fresh observation")
        // Recorded matched-26.2 Pro/underlying-trip geometry; live traits are
        // controlled because debugDescription does not serialize isHittable.
        let oldTrip = XCUIElement(full)
        oldTrip.buttons.allElementsBoundByIndex = [
            XCUIElement(CGRect(x: 16, y: 452.7, width: 370, height: 125), hittable: false)
        ]
        let pro = XCUIElement(CGRect(x: 0, y: 62, width: 402, height: 812))
        pro.staticTexts.allElementsBoundByIndex = [
            XCUIElement(CGRect(x: 32, y: 261.5, width: 278, height: 81.7), hittable: true)
        ]
        check(h.revealContainer([oldTrip, pro],
              navigationFrame: CGRect(x: 0, y: 78, width: 402, height: 54),
              viewport: CGRect(x: 6, y: 140, width: 390, height: 726)) === pro,
              "recorded modal geometry uses only the live foreground witness")
        check(select([]) == nil, "missing container rejected")
        let absent = wrapper(); absent.exists = false
        check(select([absent]) == nil, "absent wrapper rejected")
        let hidden = wrapper(); hidden.buttons.allElementsBoundByIndex[0].isHittable = false
        check(select([hidden]) == nil, "non-hittable child rejected")
        let missingChild = wrapper(); missingChild.buttons.allElementsBoundByIndex[0].exists = false
        check(select([missingChild]) == nil, "missing child rejected")
        let behindTabs = wrapper()
        behindTabs.buttons.allElementsBoundByIndex[0].frame = CGRect(x: 16, y: 791, width: 370, height: 52)
        check(select([behindTabs]) == nil, "child behind tabbar rejected")
        let clipped = wrapper()
        clipped.buttons.allElementsBoundByIndex[0].frame = CGRect(x: 380, y: 255, width: 100, height: 52)
        check(select([clipped]) == nil, "insufficient visible child width rejected")
        let tiny = wrapper()
        tiny.buttons.allElementsBoundByIndex[0].frame = CGRect(x: 32, y: 255, width: 20, height: 20)
        check(select([tiny]) === tiny, "complete smaller descendant accepted")
        let wide = wrapper(); wide.frame = CGRect(x: -100, y: 0, width: 602, height: 874)
        check(select([wide]) == nil, "wider presenting List rejected")
        let shifted = wrapper(); shifted.frame = CGRect(x: 150, y: 0, width: 250, height: 874)
        // Its midpoint must fall outside the navigation alignment tolerance.
        shifted.frame.origin.x = 240
        check(select([shifted]) == nil, "misaligned wrapper rejected")
        let shallow = wrapper(); shallow.frame = CGRect(x: 0, y: 100, width: 402, height: 100)
        check(select([shallow]) == nil, "insufficient viewport intersection rejected")
        for invalid in [CGRect.null, CGRect.infinite, CGRect.zero,
                        CGRect(x: Double.nan, y: 0, width: 402, height: 874)] {
            let item = wrapper(); item.frame = invalid
            check(select([item]) == nil, "invalid wrapper geometry rejected")
        }
        let invalidChild = wrapper(); invalidChild.buttons.allElementsBoundByIndex[0].frame = .infinite
        check(select([invalidChild]) == nil, "invalid descendant geometry rejected")
        check(h.revealContainer([good], navigationFrame: .null, viewport: viewport) == nil,
              "invalid navigation rejected in fallback")
        check(h.revealContainer([good], navigationFrame: nav, viewport: .infinite) == nil,
              "invalid viewport rejected in fallback")
        let moving = wrapper(); check(select([moving]) === moving, "initial live geometry")
        moving.buttons.allElementsBoundByIndex[0].frame = CGRect(x: 16, y: 900, width: 370, height: 52)
        check(select([moving]) == nil, "next observation rechecks current child geometry")
        let row = XCUIElement(full, hittable: true)
        let generic = XCUIElementQuery(); generic.allElementsBoundByIndex = [row]
        let typed = XCUIElementQuery(); typed.allElementsBoundByIndex = [row]
        check(h.recoveryCountTarget(generic, typed: typed) === row, "unique typed row selected")
        let alternativeType = XCUIElement(full, hittable: true)
        generic.allElementsBoundByIndex = [alternativeType]; typed.allElementsBoundByIndex = []
        check(h.recoveryCountTarget(generic, typed: typed) === alternativeType, "other representation keeps generic fallback")
        typed.allElementsBoundByIndex = [row, row]
        check(h.recoveryCountTarget(generic, typed: typed) === alternativeType, "ambiguous typed lookup keeps generic gate")
        generic.allElementsBoundByIndex = [row]; typed.allElementsBoundByIndex = [row]
        func matches() -> Bool {
            h.recoveryCountMatches(generic, row: row, identifier: "settings.count.trips", label: "Trips", count: 1)
        }
        check(matches(), "exact current count accepts")
        generic.allElementsBoundByIndex = [row, alternativeType]
        check(typed.count == 1 && !matches(), "duplicate identifier on another type rejected globally")
        generic.allElementsBoundByIndex = []
        check(!matches(), "missing global row rejected")
        generic.allElementsBoundByIndex = [row]; row.isHittable = false
        check(!matches(), "covered count row rejected")
        row.isHittable = true; row.value = "2"
        check(!matches(), "changed value is read fresh and rejected")
        row.value = 1
        check(!matches(), "non-string value rejected")
        row.value = "1"; row.label = "People"
        check(!matches(), "wrong exact label rejected")
        row.label = "Trips"; row.identifier = "settings.count.people"
        check(!matches(), "rebound snapshot identity rejected")
        row.identifier = "settings.count.trips"; row.snapshotFails = true
        check(!matches(), "snapshot failure rejects observation")
        row.snapshotFails = false
        check(matches(), "fresh restored state observed without cached value")
        print("PASS \(passed) actual List/count guards; native UI calls=0")
    }
}
'''


def fixture(source: str) -> str:
    start = source.index("    private func revealContainer(")
    end = source.index("\n    private func wait(", start)
    helper = source[start:end].replace("private func ", "func ")
    return MODEL + "\n@MainActor struct Harness {\n" + helper + "\n}\n" + CASES


def checked(argv: list[str], timeout: int) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="tripdocket-batch-scroll-") as folder:
        directory = Path(folder)
        source = directory / "WrapperGuards.swift"
        executable = directory / "wrapper-guards"
        source.write_text(fixture(SOURCE.read_text()))
        checked(["xcrun", "swiftc", "-swift-version", "6", "-strict-concurrency=complete",
                 "-parse-as-library", str(source), "-o", str(executable)], timeout=60)
        output = checked([str(executable)], timeout=30)
        if output.strip() != "PASS 45 actual List/count guards; native UI calls=0":
            raise RuntimeError("Unexpected guard count or output: " + output)
        print(output, end="")


if __name__ == "__main__":
    main()
