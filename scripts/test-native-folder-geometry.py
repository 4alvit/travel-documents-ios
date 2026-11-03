"""Exercise the real Swift blank-area helper with a small synthetic AX tree.

No Simulator, captured hierarchy, document data, or native UI execution is used.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'UITests/BatchImportUITests.swift'

FIXTURE = r'''
import Foundation
import CoreGraphics

enum Kind {
    case application, window, other, collectionView, navigationBar, keyboard
    case staticText, button, textView, cell, scrollView, image
}

@MainActor final class XCUIElementSnapshot {
    var elementType: Kind
    var identifier: String
    var label: String
    var value: Any?
    var frame: CGRect
    var children: [XCUIElementSnapshot]
    init(_ kind: Kind, _ id: String = "", _ label: String = "",
         _ frame: CGRect = .zero, _ children: [XCUIElementSnapshot] = []) {
        elementType = kind; identifier = id; self.label = label
        self.frame = frame; self.children = children
    }
}

@MainActor final class Harness {
    let name = "TripDocket-Batch-QA-00000000-0000-4000-8000-000000000001"
    let editor = XCUIElementSnapshot(.textView, "DOC.inlineRenameField", "", CGRect(x: 10, y: 290, width: 160, height: 60))
    let cell = XCUIElementSnapshot(.cell, "synthetic folder", "", CGRect(x: 10, y: 220, width: 120, height: 160))
    let files = XCUIElementSnapshot(.collectionView, "File View", "", CGRect(x: 0, y: 70, width: 400, height: 730))
    let title = XCUIElementSnapshot(.staticText, "", "On My iPhone", CGRect(x: 75, y: 100, width: 100, height: 25))
    let nav = XCUIElementSnapshot(.navigationBar, "FullDocumentManagerViewControllerNavigationBar", "", CGRect(x: 0, y: 90, width: 400, height: 110))
    let keyboard = XCUIElementSnapshot(.keyboard, "", "", CGRect(x: 0, y: 550, width: 400, height: 230))
    let browser = XCUIElementSnapshot(.other, "DOC.browsingRoot Source: com.apple.FileProvider.LocalStorage, Title: On My iPhone", "", CGRect(x: 0, y: 70, width: 400, height: 730))
    let picker = XCUIElementSnapshot(.other, "Browse View (Picker)", "", CGRect(x: 0, y: 70, width: 400, height: 730))
    let window = XCUIElementSnapshot(.window, "", "", CGRect(x: 0, y: 0, width: 400, height: 800))
    let app = XCUIElementSnapshot(.application)
    init() {
        editor.value = name; cell.children = [editor]; files.children = [cell]
        nav.children = [title]; browser.children = [nav, files]; picker.children = [browser]
        window.children = [keyboard]; app.children = [window]
    }

    // ACTUAL_HELPER

    var pickerInputOverride: XCUIElementSnapshot?
    var applicationInputOverride: XCUIElementSnapshot?
    var pickerInput: XCUIElementSnapshot { pickerInputOverride ?? picker }
    var applicationInput: XCUIElementSnapshot { applicationInputOverride ?? app }
    func point() -> (point: CGPoint, normalized: CGVector)? {
        nativeFolderBlankPoint(in: pickerInput, applicationSnapshot: applicationInput, ownedFolder: name, localTitle: "On My iPhone")
    }
}

@main struct Main {
    @MainActor static func main() {
        let name = CommandLine.arguments[1]
        let h = Harness()
        var accepts = false
        var expected: CGPoint?
        let covering = CGRect(x: 0, y: 200, width: 400, height: 220)
        switch name {
        case "application-as-picker": h.pickerInputOverride = h.app
        case "root-as-picker": h.pickerInputOverride = h.browser
        case "picker-as-application": h.applicationInputOverride = h.picker
        case "window-as-application": h.applicationInputOverride = h.window
        case "application-also-includes-picker":
            accepts = true; expected = CGPoint(x: 200, y: 300); h.window.children.append(h.picker)
        case "second-compatible-window":
            accepts = true; expected = CGPoint(x: 200, y: 300)
            h.app.children.append(XCUIElementSnapshot(.window, "", "", h.window.frame))
        case "environment-excessive-node-count":
            h.window.children += (0..<4097).map { _ in XCUIElementSnapshot(.other) }
        case "environment-excessive-depth":
            let top = XCUIElementSnapshot(.other); var current = top
            for _ in 0..<100 { let child = XCUIElementSnapshot(.other); current.children = [child]; current = child }
            h.window.children.append(top)
        case "safe-region": accepts = true; expected = CGPoint(x: 200, y: 300)
        case "translated-scaled-region":
            accepts = true; expected = CGPoint(x: 350, y: 470)
            func move(_ n: XCUIElementSnapshot) {
                n.frame = CGRect(x: n.frame.minX * 1.5 + 50, y: n.frame.minY * 1.5 + 20,
                                 width: n.frame.width * 1.5, height: n.frame.height * 1.5)
                n.children.forEach(move)
            }
            move(h.app); move(h.picker)
        case "alternate-local-title-shape":
            accepts = true; h.title.elementType = .button; h.title.label = "On My iPhone, Actions Menu"
        case "missing-picker": h.picker.identifier = "unrelated"
        case "duplicate-picker": h.picker.children.append(XCUIElementSnapshot(.other, "Browse View (Picker)"))
        case "introduction-present": h.window.children.append(XCUIElementSnapshot(.other, "UIContinuousPathIntroductionView"))
        case "missing-provider-root": h.browser.identifier = "unrelated"
        case "duplicate-provider-root": h.picker.children.append(h.browser)
        case "grid-outside-provider-root": h.browser.children = [h.nav]; h.picker.children.append(h.files)
        case "navigation-outside-provider-root": h.browser.children = [h.files]; h.picker.children.append(h.nav)
        case "missing-grid": h.files.identifier = "unrelated"
        case "duplicate-grid": h.browser.children.append(h.files)
        case "missing-navigation": h.nav.identifier = "unrelated"
        case "duplicate-navigation": h.browser.children.append(h.nav)
        case "wrong-root": h.title.label = "iCloud Drive"
        case "duplicate-root-heading": h.nav.children.append(h.title)
        case "missing-keyboard": h.window.children = []
        case "duplicate-keyboard": h.window.children.append(h.keyboard)
        case "missing-window": h.app.children = [h.keyboard]
        case "wrong-name": h.editor.value = "another folder"
        case "nonstring-name": h.editor.value = 17
        case "missing-editor": h.cell.children = []
        case "duplicate-editor": h.cell.children.append(h.editor)
        case "unowned-editor": h.cell.children = []; h.files.children.append(h.editor)
        case "nested-owner-cells": h.cell.children = [XCUIElementSnapshot(.cell, "", "", h.cell.frame, [h.editor])]
        case "nonfinite-grid": h.files.frame.origin.x = .infinity
        case "nonfinite-window": h.window.frame.origin.y = .nan
        case "empty-grid": h.files.frame.size.width = 0
        case "empty-window": h.window.frame.size.height = 0
        case "nonfinite-exclusion": h.files.children.append(XCUIElementSnapshot(.button, "", "", CGRect(x: CGFloat.nan, y: 220, width: 20, height: 20)))
        case "keyboard-covers-band": h.keyboard.frame.origin.y = 210
        case "navigation-covers-band": h.nav.frame.size.height = 400
        case "fullwidth-cell": h.cell.frame = covering
        case "button-covers-region": h.files.children.append(XCUIElementSnapshot(.button, "action", "", covering))
        case "text-covers-region": h.files.children.append(XCUIElementSnapshot(.staticText, "", "synthetic text", covering))
        case "image-covers-region": h.files.children.append(XCUIElementSnapshot(.image, "", "", covering))
        case "semantic-other-covers-region": h.files.children.append(XCUIElementSnapshot(.other, "action", "", covering))
        case "value-only-other-covers-region":
            let other = XCUIElementSnapshot(.other, "", "", covering); other.value = "synthetic"
            h.files.children.append(other)
        case "nonleaf-semantic-other-covers-region":
            let child = XCUIElementSnapshot(.staticText, "", "overlay text", CGRect(x: 5, y: 205, width: 50, height: 20))
            h.files.children.append(XCUIElementSnapshot(.other, "overlay", "", covering, [child]))
        case "excessive-node-count":
            h.picker.children += (0..<4097).map { _ in XCUIElementSnapshot(.other) }
        case "excessive-depth":
            let top = XCUIElementSnapshot(.other)
            var current = top
            for _ in 0..<100 {
                let child = XCUIElementSnapshot(.other)
                current.children = [child]; current = child
            }
            h.picker.children.append(top)
        case "second-cell-leaves-safe-column":
            accepts = true; expected = CGPoint(x: 294, y: 300)
            h.files.children.append(XCUIElementSnapshot(.cell, "second", "", CGRect(x: 180, y: 220, width: 60, height: 160)))
        case "fullwidth-editor": h.editor.frame = covering
        case "insufficient-touch-height": h.cell.frame.size.height = 25
        case "window-clips-blank": h.window.frame.size.width = 170
        case "second-window-clips-blank":
            h.app.children.append(XCUIElementSnapshot(.window, "", "", CGRect(x: 0, y: 0, width: 170, height: 800)))
        default: fatalError("Unknown synthetic case")
        }
        let result = h.point()
        guard (result != nil) == accepts else { print("FAIL \(name): \(String(describing: result))"); exit(1) }
        if let result {
            guard result.normalized.dx >= 0, result.normalized.dx <= 1,
                  result.normalized.dy >= 0, result.normalized.dy <= 1,
                  abs(h.files.frame.minX + result.normalized.dx * h.files.frame.width - result.point.x) < 0.00001,
                  abs(h.files.frame.minY + result.normalized.dy * h.files.frame.height - result.point.y) < 0.00001
            else { print("FAIL normalized point"); exit(1) }
            if let expected {
                guard abs(result.point.x - expected.x) < 0.00001,
                      abs(result.point.y - expected.y) < 0.00001 else { print("FAIL expected point"); exit(1) }
            }
        }
        print("PASS " + name)
    }
}
'''

CASES = (
    'safe-region', 'translated-scaled-region', 'alternate-local-title-shape',
    'application-as-picker', 'root-as-picker', 'picker-as-application', 'window-as-application',
    'application-also-includes-picker', 'second-compatible-window',
    'environment-excessive-node-count', 'environment-excessive-depth',
    'missing-picker', 'duplicate-picker', 'introduction-present', 'missing-grid',
    'missing-provider-root', 'duplicate-provider-root', 'grid-outside-provider-root',
    'navigation-outside-provider-root',
    'duplicate-grid', 'missing-navigation', 'duplicate-navigation', 'wrong-root',
    'duplicate-root-heading', 'missing-keyboard', 'duplicate-keyboard', 'missing-window',
    'wrong-name', 'nonstring-name', 'missing-editor', 'duplicate-editor', 'unowned-editor',
    'nested-owner-cells', 'nonfinite-grid', 'nonfinite-window', 'empty-grid', 'empty-window',
    'nonfinite-exclusion', 'keyboard-covers-band', 'navigation-covers-band',
    'fullwidth-cell', 'button-covers-region', 'text-covers-region', 'image-covers-region',
    'semantic-other-covers-region', 'value-only-other-covers-region',
    'nonleaf-semantic-other-covers-region', 'excessive-node-count', 'excessive-depth',
    'second-cell-leaves-safe-column', 'fullwidth-editor', 'insufficient-touch-height',
    'window-clips-blank', 'second-window-clips-blank',
)


class GeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = SOURCE.read_text()
        marker = '    @MainActor\n    private func nativeFolderBlankPoint('
        assert source.count(marker) == 1
        start = source.index(marker)
        end = source.index('\n    @MainActor\n    private func nativeFolderSnapshots(', start)
        helper = source[start:end]
        assert len(helper) < 65536
        cls.directory = tempfile.TemporaryDirectory(prefix='native-folder-geometry-')
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        swift = root / 'Geometry.swift'
        swift.write_text(FIXTURE.replace('    // ACTUAL_HELPER', helper))
        cls.binary = root / 'geometry-tests'
        subprocess.run(['/usr/bin/swiftc', '-swift-version', '6', '-strict-concurrency=complete',
                        '-parse-as-library', str(swift), '-o', str(cls.binary)],
                       capture_output=True, text=True, check=True, timeout=60)

    def run_case(self, case):
        result = subprocess.run([str(self.binary), case], capture_output=True,
                                text=True, check=True, timeout=5)
        self.assertEqual(result.stdout.strip(), 'PASS ' + case)


for case in CASES:
    def test(self, case=case):
        self.run_case(case)
    setattr(GeometryTests, 'test_' + case.replace('-', '_'), test)


if __name__ == '__main__':
    unittest.main()
