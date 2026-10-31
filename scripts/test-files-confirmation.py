"""Run the actual guarded one-tap confirmation helper without a simulator.

Recorded geometry is synthetic replay of the failed native layout. Dispatch and
rejection checks do not establish that native Files commits on focus loss.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'UITests/BatchImportUITests.swift'

FIXTURE = r'''import Foundation
import CoreGraphics

final class World { var actions: [String] = []; var points: [CGPoint] = []; var coordinateShift: CGFloat = 0; var coordinateCreated: (() -> Void)? }
class XCUIElement {
    enum Kind { case other, collection, cell, textView, textField, searchField, button, staticText, keyboard, alert, navigation, menu, popover }
    let world: World; let name: String; let kind: Kind
    var exists = true, isEnabled = true, isHittable = true
    var identifier: String, label: String, value: Any?
    private var storedFrame: CGRect
    var shiftAfterFirstFrameRead = false
    var shiftWhenCoordinateCreated = false
    private var frameReads = 0
    var frame: CGRect {
        get {
            frameReads += 1
            return shiftAfterFirstFrameRead && frameReads > 1 ? storedFrame.offsetBy(dx: 1, dy: 0) : storedFrame
        }
        set { storedFrame = newValue }
    }
    var children: [XCUIElement] = []
    init(_ w: World, _ name: String, _ kind: Kind = .other, _ frame: CGRect = .zero,
         identifier: String = "", label: String = "", value: String = "") {
        world = w; self.name = name; self.kind = kind; self.storedFrame = frame
        self.identifier = identifier; self.label = label; self.value = value
    }
    func descendants() -> [XCUIElement] { children.flatMap { [$0] + $0.descendants() } }
    func query(_ kind: Kind) -> XCUIElementQuery { XCUIElementQuery(descendants().filter { $0.kind == kind }) }
    var otherElements: XCUIElementQuery { query(.other) }
    var collectionViews: XCUIElementQuery { query(.collection) }
    var cells: XCUIElementQuery { query(.cell) }
    var textViews: XCUIElementQuery { query(.textView) }
    var textFields: XCUIElementQuery { query(.textField) }
    var searchFields: XCUIElementQuery { query(.searchField) }
    var buttons: XCUIElementQuery { query(.button) }
    var staticTexts: XCUIElementQuery { query(.staticText) }
    var keyboards: XCUIElementQuery { query(.keyboard) }
    var alerts: XCUIElementQuery { query(.alert) }
    var navigationBars: XCUIElementQuery { query(.navigation) }
    var menus: XCUIElementQuery { query(.menu) }
    var popovers: XCUIElementQuery { query(.popover) }
    func coordinate(withNormalizedOffset offset: CGVector) -> XCUICoordinate {
        if shiftWhenCoordinateCreated { frame = frame.offsetBy(dx: 1, dy: 0) }
        world.coordinateCreated?()
        return XCUICoordinate(self, offset)
    }
    func tap() { world.actions.append(name + ":tap") }
}
final class XCUICoordinate {
    let element: XCUIElement; let offset: CGVector; let displacement: CGVector
    init(_ element: XCUIElement, _ offset: CGVector, _ displacement: CGVector = .zero) {
        self.element = element; self.offset = offset; self.displacement = displacement
    }
    func withOffset(_ delta: CGVector) -> XCUICoordinate {
        XCUICoordinate(element, offset, CGVector(dx: displacement.dx + delta.dx, dy: displacement.dy + delta.dy))
    }
    var screenPoint: CGPoint {
        let frame = element.frame
        return CGPoint(x: frame.minX + frame.width * offset.dx + displacement.dx + element.world.coordinateShift,
                       y: frame.minY + frame.height * offset.dy + displacement.dy)
    }
    func tap() { element.world.actions.append(element.name + ":coordinate-tap"); element.world.points.append(screenPoint) }
}
final class XCUIApplication: XCUIElement {
    init(_ w: World) { super.init(w, "app", .other, CGRect(x:0,y:0,width:402,height:874)) }
}
final class XCUIElementQuery {
    var elements: [XCUIElement]
    var count: Int { elements.count }
    var element: XCUIElement { precondition(elements.count == 1); return elements[0] }
    var allElementsBoundByIndex: [XCUIElement] { elements }
    init(_ elements: [XCUIElement]) { self.elements = elements }
    func matching(identifier: String) -> XCUIElementQuery {
        XCUIElementQuery(elements.filter { $0.identifier == identifier })
    }
    func matching(_ predicate: NSPredicate) -> XCUIElementQuery {
        XCUIElementQuery(elements.filter { predicate.evaluate(with: ["label": $0.label]) })
    }
}
struct FixtureFailure: Error {}
final class Harness {
    func check(_ condition: Bool, app: XCUIApplication, _ message: String) throws {
        if !condition { throw FixtureFailure() }
    }
    // ACTUAL_HELPER
    func run(field: XCUIElement, inline: Bool, names: XCUIElementQuery,
             alerts: XCUIElementQuery, create: XCUIElementQuery,
             picker: XCUIElementQuery, navigation: XCUIElementQuery, app: XCUIApplication) throws {
        try confirmRecoveryFolderName(field, recoveryFolder: "TripDocket-Recovery-owned", inlineNaming: inline,
            inlineNames: names, alertNames: alerts, create: create, picker: picker,
            navigation: navigation, localTitle: "On My iPhone", app: app)
    }
}
@main struct Main {
    static func main() {
        let scenario = CommandLine.arguments[1], w = World(), harness = Harness()
        let app = XCUIApplication(w)
        let picker = XCUIElement(w,"picker",.other,CGRect(x:0,y:72,width:402,height:802))
        let root = XCUIElement(w,"root",.other,picker.frame,identifier:"DOC.browsingRoot Source: com.apple.FileProvider.LocalStorage, Title: On My iPhone")
        let nav = XCUIElement(w,"nav",.navigation,CGRect(x:0,y:72,width:402,height:108),identifier:"FullDocumentManagerViewControllerNavigationBar")
        let title = XCUIElement(w,"title",.staticText,CGRect(x:146.3,y:89.7,width:109.7,height:20.3),label:"On My iPhone")
        title.isHittable=false  // observed passive title while inline editing
        let files = XCUIElement(w,"files",.collection,picker.frame,identifier:"File View")
        files.isHittable=false // observed passive collection during inline editing
        let cell = XCUIElement(w,"cell",.cell,CGRect(x:10,y:190,width:122,height:189),identifier:"Folder")
        let field = XCUIElement(w,"field",.textView,CGRect(x:0,y:283,width:169,height:63),identifier:"DOC.inlineRenameField",value:"TripDocket-Recovery-owned")
        let footer = XCUIElement(w,"footer",.other,CGRect(x:0,y:434,width:402,height:38),identifier:"DOCItemCollectionViewFooterViewIdentifier")
        let label = XCUIElement(w,"count",.staticText,CGRect(x:179.3,y:434,width:43.7,height:18),label:"1 item")
        label.isHittable=false // recorded passive footer text
        let save = XCUIElement(w,"save",.button,CGRect(x:347.7,y:78,width:46.3,height:44),label:"Save")
        let export = XCUIElement(w,"export",.textField,CGRect(x:66.3,y:484,width:319.7,height:42),value:"Documents")
        let keyboard = XCUIElement(w,"keyboard",.keyboard,CGRect(x:0,y:538,width:402,height:336))
        let done = XCUIElement(w,"done",.button,CGRect(x:301.7,y:752,width:100.3,height:46),identifier:"Done",label:"done")
        let names=XCUIElementQuery([field]), alerts=XCUIElementQuery([]), create=XCUIElementQuery([done])
        let pickerQuery=XCUIElementQuery([picker]), navigation=XCUIElementQuery([nav])
        app.children=[picker,keyboard];picker.children=[root,export];root.children=[nav,files];nav.children=[save,title]
        files.children=[cell,footer];cell.children=[field];footer.children=[label];keyboard.children=[done]
        var inline=true, shouldFail=true, expected:[String]=[]
        switch scenario {
        case "inline": shouldFail=false; expected=["field:coordinate-tap"]
        case "alert": inline=false; names.elements=[]; alerts.elements=[field];shouldFail=false;expected=["done:tap"]
        case "changed-name": field.value="foreign"
        case "missing-field": field.exists=false
        case "disabled-field": field.isEnabled=false
        case "hidden-field": field.isHittable=false
        case "wrong-identifier": field.identifier="export-filename"
        case "ambiguous-inline": names.elements.append(field)
        case "missing-inline": names.elements=[]
        case "simultaneous-alert": alerts.elements=[field]
        case "missing-confirmation": create.elements=[]
        case "ambiguous-confirmation": create.elements.append(done)
        case "disabled-confirmation": done.isEnabled=false
        case "hidden-confirmation": done.isHittable=false
        case "ambiguous-alert": inline=false;names.elements=[];alerts.elements=[field,field]
        case "wrong-location": title.label="iCloud Drive"
        case "hittable-title": title.isHittable=true;shouldFail=false;expected=["field:coordinate-tap"]
        case "missing-title": title.exists=false
        case "duplicate-title": nav.children.append(title)
        case "title-outside-navigation": title.frame.origin.y=300
        case "nonfinite-title": title.frame.origin.x = .nan
        case "empty-title": title.frame.size.height=0
        case "missing-root": root.exists=false
        case "missing-navigation": nav.exists=false
        case "wrong-navigation-identity": nav.identifier="unknown"
        case "root-outside-picker": root.frame.origin.x = -1
        case "picker-outside-app": picker.frame.origin.x = -1
        case "ambiguous-navigation": navigation.elements.append(nav)
        case "missing-picker": pickerQuery.elements=[]
        case "unknown-alert": app.children.append(XCUIElement(w,"alert",.alert))
        case "wrong-provider": root.identifier="Cloud provider"
        case "ambiguous-provider": picker.children.append(root)
        case "ambiguous-collection": root.children.append(files)
        case "second-file": files.children.append(XCUIElement(w,"foreign",.cell,CGRect(x:150,y:190,width:122,height:189),identifier:"foreign, Folder"))
        case "wrong-cell": cell.identifier="foreign, Folder"
        case "different-cell-editor": cell.children=[XCUIElement(w,"replacement",.textView,field.frame,identifier:"DOC.inlineRenameField",value:"foreign")]
        case "missing-footer": footer.identifier="unknown"
        case "ambiguous-footer": files.children.append(footer)
        case "wrong-count-label": label.label="2 items"
        case "second-footer-label": footer.children.append(XCUIElement(w,"second",.staticText))
        case "passive-footer-label": label.isHittable=false;shouldFail=false;expected=["field:coordinate-tap"]
        case "passive-collection": files.isHittable=false;shouldFail=false;expected=["field:coordinate-tap"]
        case "disabled-collection": files.isEnabled=false
        case "missing-collection": files.exists=false
        case "coordinate-shift": w.coordinateShift=2
        case "coordinate-nan": w.coordinateShift = .nan
        case "late-collection-move": w.coordinateCreated = { files.frame = files.frame.offsetBy(dx:1,dy:0) }
        case "late-editor-move": field.shiftWhenCoordinateCreated=true
        case "zero-editor": field.frame.size.width=0
        case "nonfinite-editor": field.frame.origin.x = .nan
        case "editor-outside-collection": field.frame.origin.y=60
        case "editor-unavailable-at-coordinate": w.coordinateCreated = { field.isHittable=false }
        case "unknown-menu": app.children.append(XCUIElement(w,"menu",.menu))
        case "unknown-popover": app.children.append(XCUIElement(w,"popover",.popover))
        case "hit-region-outside-footer": footer.frame.size.height=12
        case "missing-footer-label": label.exists=false
        case "interactive-footer": footer.children.append(XCUIElement(w,"unexpected",.button))
        case "label-outside-footer": label.frame.origin.x = -1
        case "label-outside-collection": files.frame=CGRect(x:0,y:0,width:100,height:100)
        case "label-outside-app": app.frame=CGRect(x:0,y:0,width:100,height:100)
        case "late-footer-move": label.shiftAfterFirstFrameRead=true
        case "zero-label": label.frame.size.width=0
        case "nonfinite-label": label.frame.origin.x = .nan
        case "late-control-move": save.shiftAfterFirstFrameRead=true
        case "nonfinite-exclusion": save.frame.origin.y = .nan
        case "save-overlap": save.frame=label.frame
        case "save-near-margin": save.frame=CGRect(x:label.frame.maxX+7,y:434,width:20,height:20)
        case "file-overlap": cell.frame=label.frame
        case "editor-overlap": field.frame=label.frame
        case "keyboard-overlap": keyboard.frame=label.frame
        case "export-overlap": export.frame=label.frame
        case "navigation-overlap": nav.frame=label.frame
        case "inventory-overflow": picker.children += (0..<65).map { XCUIElement(w,"extra\($0)",.button) }
        default: fatalError("Unknown synthetic scenario")
        }
        var failed=false
        do { try harness.run(field:field,inline:inline,names:names,alerts:alerts,create:create,picker:pickerQuery,navigation:navigation,app:app) }
        catch { failed=true }
        guard failed == shouldFail, w.actions == expected else { print("FAIL " + scenario); exit(1) }
        if !shouldFail && inline {
            guard w.points.count == 1, abs(w.points[0].x - 201.15) < 0.001,
                  abs(w.points[0].y - 443) < 0.001 else { print("FAIL point " + scenario); exit(1) }
        } else if !w.points.isEmpty { print("FAIL unexpected point " + scenario); exit(1) }
        print("PASS " + scenario)
    }
}
'''

class ConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        source = SOURCE.read_text()
        start = source.index('    private func confirmRecoveryFolderName(')
        end = source.index('    private func presentRecoverySave(', start)
        root = Path(cls.directory.name)
        path = root / 'Confirmation.swift'
        path.write_text(FIXTURE.replace('    // ACTUAL_HELPER', source[start:end]))
        cls.binary = root / 'confirmation-tests'
        result = subprocess.run(['/usr/bin/swiftc', '-parse-as-library', str(path), '-o', str(cls.binary)],
                       capture_output=True, text=True, timeout=45)
        if result.returncode: raise RuntimeError(result.stderr)

    def run_case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True,
                                check=True, timeout=5)
        self.assertEqual(result.stdout.strip(), 'PASS ' + name)

    def test_call_keeps_exact_name_and_existing_postcondition(self):
        source = SOURCE.read_text()
        start = source.index('    func testRecoveryCreateOwnedFilesDestination')
        end = source.index('    private func confirmRecoveryFolderName(', start)
        body = source[start:end]
        typed = body.index('field.typeText(recoveryFolder)')
        verified = body.index('try check(field.value as? String == recoveryFolder', typed)
        before = body.index('observeCommit("before_done")', verified)
        dispatch = body.index('try confirmRecoveryFolderName(', before)
        after = body.index('observeCommit("after_done")', dispatch)
        postcondition = body.index('inlineNames.count == 0 &&', after)
        self.assertLess(typed, verified)
        self.assertLess(verified, before)
        self.assertLess(before, dispatch)
        self.assertLess(dispatch, after)
        self.assertLess(after, postcondition)
        for operation in ('.tap()', '.press(', '.typeText(', '.typeKey('):
            self.assertNotIn(operation, body[verified:dispatch])
        self.assertEqual(body.count('try confirmRecoveryFolderName('), 1)
        self.assertIn('self.isRecoveryFolder(recoveryFolder, navigation: navigation.element)', body[postcondition:])
        self.assertIn('(directory.count == 1 && directory.element.isHittable)', body[postcondition:])
        self.assertIn('let deadline = ContinuousClock.now.advanced(by: .seconds(15))', source)
        self.assertIn('python3 -B scripts/test-files-confirmation.py', (ROOT / '.github/workflows/ci.yml').read_text())
        helper = source[end:source.index('    private func presentRecoverySave(',end)]
        self.assertEqual(helper.count('.tap()'), 2)  # mutually exclusive alert and inline paths
        self.assertNotIn('.typeKey(',helper)
        self.assertNotIn('.typeText(',helper)
        self.assertEqual(helper.count('coordinate(withNormalizedOffset:'), 1)
        self.assertNotIn('files.isHittable', helper)
        self.assertIn('field.coordinate(withNormalizedOffset:', helper)
        self.assertEqual(helper.count('.withOffset(offset)'), 1)
        self.assertIn('coordinate.screenPoint', helper)

    def test_passive_collection(self): self.run_case('passive-collection')
    def test_late_editor_move(self): self.run_case('late-editor-move')
    def test_zero_editor(self): self.run_case('zero-editor')
    def test_nonfinite_editor(self): self.run_case('nonfinite-editor')
    def test_editor_outside_collection(self): self.run_case('editor-outside-collection')
    def test_editor_unavailable_at_coordinate(self): self.run_case('editor-unavailable-at-coordinate')
    def test_disabled_collection(self): self.run_case('disabled-collection')
    def test_missing_collection(self): self.run_case('missing-collection')
    def test_late_control_move(self): self.run_case('late-control-move')
    def test_coordinate_shift(self): self.run_case('coordinate-shift')
    def test_coordinate_nan(self): self.run_case('coordinate-nan')
    def test_late_collection_move(self): self.run_case('late-collection-move')
    def test_unknown_menu(self): self.run_case('unknown-menu')
    def test_unknown_popover(self): self.run_case('unknown-popover')
    def test_hit_region_outside_footer(self): self.run_case('hit-region-outside-footer')
    def test_inline(self): self.run_case('inline')
    def test_alert(self): self.run_case('alert')
    def test_changed_name(self): self.run_case('changed-name')
    def test_missing_field(self): self.run_case('missing-field')
    def test_disabled_field(self): self.run_case('disabled-field')
    def test_hidden_field(self): self.run_case('hidden-field')
    def test_wrong_identifier(self): self.run_case('wrong-identifier')
    def test_ambiguous_inline(self): self.run_case('ambiguous-inline')
    def test_missing_inline(self): self.run_case('missing-inline')
    def test_simultaneous_alert(self): self.run_case('simultaneous-alert')
    def test_missing_confirmation(self): self.run_case('missing-confirmation')
    def test_ambiguous_confirmation(self): self.run_case('ambiguous-confirmation')
    def test_disabled_confirmation(self): self.run_case('disabled-confirmation')
    def test_hidden_confirmation(self): self.run_case('hidden-confirmation')
    def test_ambiguous_alert(self): self.run_case('ambiguous-alert')
    def test_hittable_title(self): self.run_case('hittable-title')
    def test_missing_title(self): self.run_case('missing-title')
    def test_duplicate_title(self): self.run_case('duplicate-title')
    def test_title_outside_navigation(self): self.run_case('title-outside-navigation')
    def test_nonfinite_title(self): self.run_case('nonfinite-title')
    def test_empty_title(self): self.run_case('empty-title')
    def test_missing_root(self): self.run_case('missing-root')
    def test_missing_navigation(self): self.run_case('missing-navigation')
    def test_wrong_navigation_identity(self): self.run_case('wrong-navigation-identity')
    def test_root_outside_picker(self): self.run_case('root-outside-picker')
    def test_picker_outside_app(self): self.run_case('picker-outside-app')
    def test_wrong_location(self): self.run_case('wrong-location')
    def test_ambiguous_navigation(self): self.run_case('ambiguous-navigation')
    def test_missing_picker(self): self.run_case('missing-picker')
    def test_unknown_alert(self): self.run_case('unknown-alert')
    def test_wrong_provider(self): self.run_case('wrong-provider')
    def test_ambiguous_provider(self): self.run_case('ambiguous-provider')
    def test_ambiguous_collection(self): self.run_case('ambiguous-collection')
    def test_second_file(self): self.run_case('second-file')
    def test_wrong_cell(self): self.run_case('wrong-cell')
    def test_different_cell_editor(self): self.run_case('different-cell-editor')
    def test_missing_footer(self): self.run_case('missing-footer')
    def test_ambiguous_footer(self): self.run_case('ambiguous-footer')
    def test_wrong_count_label(self): self.run_case('wrong-count-label')
    def test_second_footer_label(self): self.run_case('second-footer-label')
    def test_passive_footer_label(self): self.run_case('passive-footer-label')
    def test_missing_footer_label(self): self.run_case('missing-footer-label')
    def test_interactive_footer(self): self.run_case('interactive-footer')
    def test_label_outside_footer(self): self.run_case('label-outside-footer')
    def test_label_outside_collection(self): self.run_case('label-outside-collection')
    def test_label_outside_app(self): self.run_case('label-outside-app')
    def test_late_footer_move(self): self.run_case('late-footer-move')
    def test_zero_label(self): self.run_case('zero-label')
    def test_nonfinite_label(self): self.run_case('nonfinite-label')
    def test_nonfinite_exclusion(self): self.run_case('nonfinite-exclusion')
    def test_save_overlap(self): self.run_case('save-overlap')
    def test_save_near_margin(self): self.run_case('save-near-margin')
    def test_file_overlap(self): self.run_case('file-overlap')
    def test_editor_overlap(self): self.run_case('editor-overlap')
    def test_keyboard_overlap(self): self.run_case('keyboard-overlap')
    def test_export_overlap(self): self.run_case('export-overlap')
    def test_navigation_overlap(self): self.run_case('navigation-overlap')
    def test_inventory_overflow(self): self.run_case('inventory-overflow')


class SDKSourceTests(unittest.TestCase):
    def test_complete_file_typechecks_without_fixture_scope(self):
        sdk = subprocess.run(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-path'],
                             capture_output=True, text=True, check=True, timeout=15).stdout.strip()
        platform = subprocess.run(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-platform-path'],
                                  capture_output=True, text=True, check=True, timeout=15).stdout.strip()
        frameworks = str(Path(platform) / 'Developer/Library/Frameworks')
        result = subprocess.run(
            ['xcrun', 'swiftc', '-typecheck', '-swift-version', '6',
             '-target', 'arm64-apple-ios17.0-simulator', '-sdk', sdk,
             '-F', frameworks, '-F', str(Path(sdk) / 'Developer/Library/Frameworks'),
             '-I', str(Path(platform) / 'Developer/usr/lib'), str(SOURCE)],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
