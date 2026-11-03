#!/usr/bin/env python3
"""Exercise actual snapshot helpers against deterministic, actor-isolated trees.

No application, XCTest session, or Simulator is started. The model deliberately
marks snapshot attributes MainActor-isolated, matching the SDK contract. Native
UI geometry, accessibility, and timing still require the separate UI test lane.
"""
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "UITests/LocalizationUITests.swift"

MODEL = r'''
import Foundation
import CoreGraphics
@MainActor class XCUIElement {
 enum ElementType { case sheet, application, window, navigationBar, tabBar, collectionView, scrollView, staticText, button, other }
 var isHittable = true; var exists = true
}
@MainActor final class Query {
 let element = XCUIElement()
 subscript(_ key: String) -> XCUIElement { element }
}
@MainActor protocol XCUIElementSnapshot {
 var elementType: XCUIElement.ElementType { get }
 var identifier: String { get }
 var label: String { get }
 var frame: CGRect { get }
 var children: [XCUIElementSnapshot] { get }
}
@MainActor final class Snapshot: XCUIElementSnapshot {
 let elementType: XCUIElement.ElementType
 let identifier: String
 let label: String
 let frame: CGRect
 var children: [XCUIElementSnapshot]
 init(_ type: XCUIElement.ElementType, _ id: String = "", _ label: String = "", _ frame: CGRect = CGRect(x:0,y:0,width:400,height:800), _ children: [XCUIElementSnapshot] = []) {
  self.elementType=type; self.identifier=id; self.label=label; self.frame=frame; self.children=children
 }
}
@MainActor final class XCUIApplication {
 let navigationBars = Query(); let tabBars = Query()
 let root: XCUIElementSnapshot; var fail = false
 init(_ root: XCUIElementSnapshot) { self.root=root }
 func snapshot() throws -> XCUIElementSnapshot { if fail { throw Failure() }; return root }
 struct Failure: Error {}
}
'''

CASES = r'''

@main struct GuardRunner {
 @MainActor static func main() {
 let h=Harness(); var passed=0
 func check(_ condition:Bool,_ name:String) { guard condition else { print("FAIL \(name)"); exit(1) }; passed += 1 }
 let windowFrame=CGRect(x:0,y:0,width:402,height:874)
 let dialogFrame=CGRect(x:81,y:72,width:240,height:745)
 let bodyFrame=CGRect(x:81,y:72,width:240,height:542.333333)
 let warningFrame=CGRect(x:111,y:577,width:180,height:2610.666667)
 let actionFrame=CGRect(x:81,y:614.333333,width:240,height:202.666667)
 let buttonFrame=CGRect(x:97,y:630.333333,width:208,height:170.666667)
 func fixture() -> XCUIApplication {
  let warning=Snapshot(.staticText,"",h.backupWarningText,warningFrame)
  let body=Snapshot(.scrollView,"","",bodyFrame,[Snapshot(.other,"","",bodyFrame,[warning])])
  let button=Snapshot(.button,"",h.exportActionTitle,buttonFrame)
  let action=Snapshot(.scrollView,"","",actionFrame,[button])
  let sheet=Snapshot(.sheet,"",h.backupWarningTitle,dialogFrame,[body,action])
  let window=Snapshot(.window,"","",windowFrame,[sheet])
  return XCUIApplication(Snapshot(.application,"","",windowFrame,[window,Snapshot(.window,"","",windowFrame)]))
 }
 func sheet(_ app:XCUIApplication)->Snapshot { app.root.children[0].children[0] as! Snapshot }
 func body(_ app:XCUIApplication)->Snapshot { sheet(app).children[0] as! Snapshot }
 func action(_ app:XCUIApplication)->Snapshot { sheet(app).children[1] as! Snapshot }
 func observe(_ app:XCUIApplication)->Harness.BackupWarningObservation? { h.backupWarningObservation(in:app) }
 let good=observe(fixture())!
 check(good.bodyFrame==bodyFrame && good.warningFrame==warningFrame && good.actionFrame==actionFrame && good.buttonFrame==buttonFrame && good.dialogFrame==dialogFrame && good.windowFrame==windowFrame,"retained native two-pane/two-equal-window geometry")
 let single=fixture(); (single.root as! Snapshot).children.removeLast();check(observe(single) != nil,"single window")
 let unequal=fixture();(unequal.root as! Snapshot).children[1]=Snapshot(.window,"","",CGRect(x:0,y:0,width:400,height:800));check(observe(unequal)==nil,"unequal windows fall back")
 let duplicate=fixture();(duplicate.root.children[0] as! Snapshot).children.append(sheet(duplicate));check(observe(duplicate)==nil,"duplicate sheet falls back")
 let missing=fixture();(missing.root.children[0] as! Snapshot).children=[];check(observe(missing)==nil,"missing sheet falls back")
 let wrongText=fixture();body(wrongText).children=[Snapshot(.staticText,"","short warning",warningFrame)];check(observe(wrongText)==nil,"wrong complete label falls back")
 let wrongType=fixture();body(wrongType).children=[Snapshot(.button,"",h.backupWarningText,warningFrame)];check(observe(wrongType)==nil,"matching label wrong type falls back")
 let duplicateText=fixture();body(duplicateText).children.append(Snapshot(.staticText,"",h.backupWarningText,warningFrame));check(observe(duplicateText)==nil,"duplicate warning falls back")
 let duplicateButton=fixture();action(duplicateButton).children.append(Snapshot(.button,"",h.exportActionTitle,buttonFrame));check(observe(duplicateButton)==nil,"duplicate button falls back")
 let shared=fixture();body(shared).children.append(action(shared).children[0]);sheet(shared).children.removeLast();check(observe(shared)==nil,"combined body/action pane falls back")
 let nested=fixture();let originalBody=body(nested);sheet(nested).children[0]=Snapshot(.scrollView,"","",bodyFrame,[originalBody]);check(observe(nested)==nil,"two matching ancestor panes fall back")
 let invalid=fixture();body(invalid).children=[Snapshot(.staticText,"",h.backupWarningText,.infinite)];check(observe(invalid)==nil,"infinite geometry falls back")
 let failed=fixture();failed.fail=true;check(observe(failed)==nil,"snapshot error falls back")
 let deep=fixture();var parent=body(deep);for _ in 0..<61 {let child=Snapshot(.other);parent.children.append(child);parent=child};check(observe(deep)==nil,"bounded depth")
 let wide=fixture();body(wide).children += (0..<2001).map {_ in Snapshot(.other)};check(observe(wide)==nil,"bounded node count")
 let changed=fixture();let first=observe(changed)!;body(changed).children=[Snapshot(.staticText,"",h.backupWarningText,warningFrame.offsetBy(dx:0,dy:-100))];let second=observe(changed)!;check(first.warningFrame != second.warningFrame && second.warningFrame==warningFrame.offsetBy(dx:0,dy:-100),"each observation uses current snapshot geometry")
 let swapped=fixture();let retainedBodyIndex=0;sheet(swapped).children.swapAt(0,1)
 let retainedWarning=XCUIElement()
 retainedWarning.exists=(h.snapshotNodes(sheet(swapped).children[retainedBodyIndex]) ?? []).contains { $0.elementType == .staticText && $0.label == h.backupWarningText }
 check(observe(swapped) != nil && !retainedWarning.exists,"reordered panes preserve global warning but invalidate retained scoped query")
 do { _ = try h.boundWarningViewport(in:swapped,warning:retainedWarning); print("FAIL reordered retained body must throw"); exit(1) } catch { check(true,"actual fast path rejects swapped retained-body index") }
 retainedWarning.exists=true;do { check(try h.boundWarningViewport(in:fixture(),warning:retainedWarning) != nil,"bound current body accepts geometry") } catch { print("FAIL bound body unexpectedly rejected"); exit(1) }
 let view=XCUIApplication(Snapshot(.application,"","",windowFrame,[Snapshot(.window,"","",windowFrame,[Snapshot(.navigationBar,"Настройки","",CGRect(x:0,y:62,width:402,height:54)),Snapshot(.tabBar,"","",CGRect(x:0,y:791,width:402,height:83))])]))
 check(h.snapshotViewport(in:view,navigationTitle:"Настройки")==CGRect(x:2,y:116,width:398,height:675),"viewport uses live visible bars")
 view.navigationBars.element.isHittable=false;view.tabBars.element.isHittable=false
 check(h.snapshotViewport(in:view,navigationTitle:"Настройки")==windowFrame.insetBy(dx:2,dy:2),"live unhittable bars do not crop")
 (view.root.children[0] as! Snapshot).children.append(Snapshot(.navigationBar,"Настройки"));check(h.snapshotViewport(in:view,navigationTitle:"Настройки")==nil,"ambiguous navigation falls back")
 let viewport=bodyFrame.intersection(dialogFrame).intersection(windowFrame).insetBy(dx:2,dy:2)
 let drag=h.backupWarningDrag(viewport:viewport,frame:warningFrame,coveredThrough:35.333333,bodyFrame:bodyFrame)!
 check(viewport.contains(drag.start) && viewport.contains(drag.end) && drag.start.y > drag.end.y,"both upward endpoints inside exact text viewport")
 check(drag.start.y-drag.end.y > 480 && drag.start.y-drag.end.y < 490,"measured538pt viewport avoids old160pt cap")
 check(viewport.height-(drag.start.y-drag.end.y) >= 48,"retains minimum48pt geometric overlap")
 check(drag.start.y < actionFrame.minY && drag.end.y < actionFrame.minY,"gesture stays above separate native actions")
 let reverse=h.backupWarningDrag(viewport:viewport,frame:warningFrame.offsetBy(dx:0,dy:-1000),coveredThrough:0,bodyFrame:bodyFrame)!
 check(reverse.start.y < reverse.end.y && viewport.contains(reverse.start) && viewport.contains(reverse.end),"missed prefix scrolls back inside pane")
 let small=CGRect(x:10,y:20,width:100,height:81)
 let smallDrag=h.backupWarningDrag(viewport:small,frame:CGRect(x:15,y:90,width:80,height:1000),coveredThrough:11,bodyFrame:small.insetBy(dx:-2,dy:-2))!
 check(small.contains(smallDrag.start) && small.contains(smallDrag.end) && small.height-(smallDrag.start.y-smallDrag.end.y) >= small.height*0.25,"small viewport endpoints and proportional overlap")
 check(h.backupWarningDrag(viewport:viewport,frame:warningFrame,coveredThrough:35,bodyFrame:bodyFrame.offsetBy(dx:0,dy:10))==nil,"moved live body cannot contain old viewport")
 check(h.backupWarningDrag(viewport:.infinite,frame:warningFrame,coveredThrough:35,bodyFrame:bodyFrame)==nil,"invalid viewport rejected")
 check(h.backupWarningDrag(viewport:viewport,frame:.null,coveredThrough:35,bodyFrame:bodyFrame)==nil,"invalid label rejected")
 check(h.backupWarningDrag(viewport:viewport,frame:warningFrame,coveredThrough:.nan,bodyFrame:bodyFrame)==nil,"nonfinite coverage rejected")
 check(h.backupWarningDrag(viewport:viewport,frame:warningFrame,coveredThrough:-1,bodyFrame:bodyFrame)==nil,"negative coverage rejected")
 check(h.backupWarningDrag(viewport:viewport,frame:warningFrame,coveredThrough:warningFrame.height,bodyFrame:bodyFrame)==nil,"completed label needs no extra drag")
 check(h.backupWarningDrag(viewport:CGRect(x:83,y:74,width:44,height:538),frame:warningFrame,coveredThrough:35,bodyFrame:bodyFrame)==nil,"narrow viewport rejected")
 check(h.coverage([0...35,100...500,500...2611])==35,"first and final portions cannot bridge an unseen middle")
 check(h.coverage([500...900,0...100,90...510])==900,"actual overlapping slices merge independent of order")
 var measured=warningFrame; var slices:[ClosedRange<CGFloat>]=[]; var count=0
 for _ in 0..<19 {
  let visible=measured.intersection(viewport)
  if !visible.isNull && !visible.isEmpty { slices.append(max(0,visible.minY-measured.minY)...min(measured.height,visible.maxY-measured.minY)) }
  count += 1; let covered=h.coverage(slices)
  if covered >= measured.height-1 { break }
  guard let motion=h.backupWarningDrag(viewport:viewport,frame:measured,coveredThrough:covered,bodyFrame:bodyFrame) else { print("FAIL synthetic motion unavailable");exit(1) }
  // Synthetic response uses measured C13 10.333pt touch deadband. It is
  // geometry coverage evidence only, not a prediction of native timing.
  let delta=motion.end.y-motion.start.y
  let moved=delta < 0 ? min(0,delta+10.333333) : max(0,delta-10.333333)
  measured=measured.offsetBy(dx:0,dy:moved)
 }
 check(h.coverage(slices)>=measured.height-1 && count<=8,"synthetic C13 geometry covers every interval in at most8captures")
 check(h.coverage(Array(repeating:0...35,count:19))==35,"stationary native response never becomes covered")
 print("PASS \(passed) extracted-helper actor-isolated offline guards; native app calls=0")
 }
}
'''

def declaration(source: str, marker: str) -> str:
    """Extract a balanced declaration; subsequent Swift compilation is strict."""
    start = source.index(marker)
    position = source.index("{", start) + 1
    depth = 1
    while depth:
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
        position += 1
    return source[start:position].replace("private ", "")


def fixture(source: str) -> str:
    markers = [
        "    private func snapshotViewport(",
        "    private func backupWarningDrag(",
        "    private struct BackupWarningObservation",
        "    private func backupWarningObservation(",
        "    private func snapshotNodes(",
        "    private func finiteFrame(",
    ]
    parts = [declaration(source, marker) for marker in markers]
    constants = []
    for name in ("backupWarningTitle", "backupWarningText", "exportActionTitle"):
        matches = [line for line in source.splitlines() if f"private let {name} =" in line]
        if len(matches) != 1:
            raise ValueError(f"Expected one literal definition for {name}")
        constants.append(matches[0].replace("private ", ""))
    # Execute the real fast branch too: global tree uniqueness alone cannot
    # prove that the retained index-based body query still names that pane.
    warning = declaration(source, "    private func verifyCompleteBackupWarning(")
    coverage_start = warning.index("            var coveredThrough: CGFloat = 0")
    coverage_end = warning.index('            print("WARNING_COVERAGE', coverage_start)
    parts.append("func coverage(_ slices: [ClosedRange<CGFloat>]) -> CGFloat {\n"
                 + warning[coverage_start:coverage_end] + "\nreturn coveredThrough\n}")
    start = warning.index("            if let observation = backupWarningObservation(in: app) {")
    end = warning.index("            } else {", start) + len("            }")
    branch = warning[start:end]
    parts.append("""
    func boundWarningViewport(in app: XCUIApplication, warning: XCUIElement) throws -> CGRect? {
        let viewport: CGRect
        let frame: CGRect
    """ + branch + """ else { return nil }
        _ = frame
        return viewport
    }
    func require(_ value: Bool, app: XCUIApplication, _ message: String) throws {
        if !value { throw XCUIApplication.Failure() }
    }
    """)
    return MODEL + "@MainActor struct Harness {\n" + "\n".join(constants + parts) + "\n}\n" + CASES


def checked(argv: list[str], timeout: int) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout


def main() -> None:
    swift = fixture(SOURCE.read_text())
    with tempfile.TemporaryDirectory(prefix="tripdocket-localization-snapshots-") as folder:
        directory = Path(folder)
        source = directory / "SnapshotGuards.swift"
        executable = directory / "snapshot-guards"
        source.write_text(swift)
        checked([
            "xcrun", "swiftc", "-swift-version", "6", "-strict-concurrency=complete",
            "-parse-as-library", str(source), "-o", str(executable),
        ], timeout=60)
        output = checked([str(executable)], timeout=30)
        if output.strip() != "PASS 39 extracted-helper actor-isolated offline guards; native app calls=0":
            raise RuntimeError("Unexpected localization guard count or output: " + output)
        print(output, end="")


if __name__ == "__main__":
    main()
