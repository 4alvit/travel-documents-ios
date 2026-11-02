#!/usr/bin/env python3
"""Exercise the actual List-wrapper selection helper without native UI calls."""
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "UITests/BatchImportUITests.swift"

MODEL = r'''
import Foundation
import CoreGraphics
@MainActor final class Query {
    var allElementsBoundByIndex: [XCUIElement] = []
}
@MainActor final class XCUIElement {
    var exists = true
    var isHittable = false
    var frame: CGRect
    let buttons = Query()
    let staticTexts = Query()
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
        check(select([wrapper(), wrapper()]) == nil, "two geometric wrappers rejected")
        check(select([wrapper(), XCUIElement(full)]) == nil, "ambiguous wrapper rejected before child selection")
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
        print("PASS \(passed) actual List-wrapper guards; native UI calls=0")
    }
}
'''


def fixture(source: str) -> str:
    start = source.index("    private func revealContainer(")
    end = source.index("\n    private func wait(", start)
    helper = source[start:end].replace("private func revealContainer", "func revealContainer", 1)
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
        if output.strip() != "PASS 25 actual List-wrapper guards; native UI calls=0":
            raise RuntimeError("Unexpected guard count or output: " + output)
        print(output, end="")


if __name__ == "__main__":
    main()
