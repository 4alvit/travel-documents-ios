#!/usr/bin/env python3
"""Exercise actual reading geometry and acceptance using observed boundary frames.

No application, XCTest session, or Simulator is started. Native scrolling still
requires its separate UI test lane.
"""
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "UITests/PrivacySupportUITests.swift"
source = SOURCE.read_text()

def declaration(source, marker):
 start=source.index(marker); end=source.index('{',start)+1; level=1
 while level:
  level += (source[end]=='{')-(source[end]=='}');end+=1
 return source[start:end].replace('private ','')
def acceptance(source):
 start=source.index('            let tallReadingText =')
 end=source.index('                return ScrollObservation(',start)
 branch=source[start:end]
 return '''func accepts(_ frame: CGRect, _ visibleBounds: CGRect, readingPrefix: Bool = true, exists: Bool = true, hittable: Bool = true) -> Bool {
 let target=Target(isHittable:hittable); let preferWholeFrame=true
 '''+branch+''' return true\n }\n _ = tallReadingText\n return false\n}\n'''
helpers='\n'.join(declaration(source,'    private func '+name+'(') for name in ['textReadingViewport','readingStartIsVisible','visiblePortion'])
fixture='''import Foundation
import CoreGraphics
struct Target { let isHittable: Bool }
@MainActor class New {\n'''+helpers+'\n'+acceptance(source)+'''\n}
@main struct Runner {
 @MainActor static func main() {
 let n=New();var count=0
 func check(_ condition: Bool, _ name:String) { guard condition else { print("FAIL \\(name)");exit(1) }; count += 1 }
 let bounds=CGRect(x:2,y:140,width:1028,height:1234)
 let current=CGRect(x:20,y:1322.5,width:992,height:52)
 let prior=CGRect(x:20,y:1313.5,width:992,height:52)
 let read=n.textReadingViewport(bounds)
 check(read==CGRect(x:3,y:141,width:1026,height:1232),"exact retained read viewport")
 check(bounds.insetBy(dx:-1,dy:-1).contains(current) && !n.accepts(current,bounds),"observed clipped short text must scroll despite expanded hit-test containment")
 check(current.intersection(read).height==50.5 && current.height-1>50.5,"actual 1.5pt missing coverage reproduces failure")
 check(n.accepts(prior,bounds),"fully contained short text remains accepted")
 check(n.accepts(CGRect(x:20,y:1321,width:992,height:52),bounds),"short text exactly at lower read edge")
 check(!n.accepts(CGRect(x:20,y:1321.5,width:992,height:52),bounds),"half point outside lower read edge keeps scrolling")
 check(n.accepts(CGRect(x:20,y:141,width:992,height:52),bounds),"short text exactly at upper read edge")
 check(!n.accepts(CGRect(x:20,y:140.5,width:992,height:52),bounds),"short prefix half point outside read edge")
 check(!n.accepts(CGRect(x:2.5,y:200,width:1026,height:52),bounds),"short text horizontally outside read edge")
 check(!n.accepts(prior,bounds,exists:false),"missing target remains rejected")
 check(!n.accepts(prior,bounds,hittable:false),"nonhittable target remains rejected")
 check(n.accepts(CGRect(x:20,y:141,width:992,height:1600),bounds,readingPrefix:false),"oversized ordinary card retains visible-prefix acceptance")
 check(!n.accepts(CGRect(x:20,y:1375,width:992,height:1600),bounds,readingPrefix:false),"oversized card entirely below viewport remains rejected")
 check(n.accepts(current,bounds,readingPrefix:false),"ordinary action tolerance unchanged")
 check(n.accepts(CGRect(x:20,y:141,width:992,height:1600),bounds),"tall prefix at first allowed point")
 check(n.accepts(CGRect(x:20,y:188,width:992,height:1600),bounds),"tall prefix at last allowed point")
 check(!n.accepts(CGRect(x:20,y:140.5,width:992,height:1600),bounds),"tall prefix above viewport rejected")
 check(!n.accepts(CGRect(x:20,y:188.5,width:992,height:1600),bounds),"tall prefix below prefix window rejected")
 check(n.accepts(CGRect(x:20,y:141,width:992,height:1233),bounds),"text taller than reader but shorter than raw viewport follows tall coverage")
 check(!n.accepts(.zero,bounds) && !n.accepts(prior,.zero),"empty target and empty bounds rejected")
 var invariant=true
 for y in stride(from:139.0,through:1376.0,by:0.5) {
  let f=CGRect(x:20,y:y,width:992,height:52)
  if n.accepts(f,bounds) && !read.contains(f) { invariant=false }
 }
 check(invariant,"accepted short frames always fit exact read region across 2475 positions")
 print("PASS \\(count) actual-helper guards; native app calls=0")
 }
}
'''
# All live read branches use the same inset that the acceptance guard checks.
reader=declaration(source,'    private func readWholeText(')
assert reader.count('textReadingViewport(')==3
with tempfile.TemporaryDirectory(prefix='tripdocket-reading-geometry-') as tmp:
    swift = Path(tmp) / "guards.swift"
    binary = Path(tmp) / "guards"
    swift.write_text(fixture)
    subprocess.run(["xcrun", "swiftc", "-swift-version", "6",
                    "-strict-concurrency=complete", "-parse-as-library",
                    str(swift), "-o", str(binary)], check=True, timeout=90)
    subprocess.run([str(binary)], check=True, timeout=30)

# Execute the actual fixture-admission block with lazy, missing and offscreen
# rows. The bounded scroll implementation is unchanged; this tests its call
# order and direction without starting XCTest or changing StoreKit state.
start = source.index('        let free = app.staticTexts[copy.freeTitle]')
end = source.index('        entry.tap()', start)
admission = source[start:end]
fixture = '''import Foundation
enum Failure: Error { case rejected }
enum Kind { case staticText, button }
struct SnapshotMatch { let type: Kind; let key: String }
final class Element {
 var exists = false
 var isHittable = false
 var firstMatch: Element { self }
 func waitForExistence(timeout: Double) -> Bool {
  precondition(timeout == 5)
  return exists
 }
}
struct Query {
 let element: Element
 subscript(_ key: String) -> Element { element }
}
struct App {
 let free = Element()
 let entry = Element()
 var staticTexts: Query { Query(element: free) }
 var buttons: Query { Query(element: entry) }
}
struct Copy { let freeTitle = "Free card"; let settings = "Settings" }
@MainActor final class Harness {
 let app = App()
 let copy = Copy()
 let mode: String
 var events: [String] = []
 init(_ mode: String) {
  self.mode = mode
  if mode == "visible" { app.free.exists = true; app.free.isHittable = true }
 }
 func scrollTo(_ target: Element, in app: App, navigationTitle: String,
               description: String, preferWholeFrame: Bool, searchDown: Bool = true,
               snapshotMatch: SnapshotMatch) async throws {
  precondition(navigationTitle == copy.settings && preferWholeFrame)
  if target === app.free {
   events.append("free-down")
   precondition(searchDown && snapshotMatch.type == .staticText && snapshotMatch.key == copy.freeTitle)
   if mode == "scroll-fails" { throw Failure.rejected }
   target.exists = mode != "missing-free"
   target.isHittable = mode != "nonhittable-free"
  } else {
   events.append(searchDown ? "entry-down" : "entry-up")
   guard !searchDown else { throw Failure.rejected }
   precondition(target === app.entry && snapshotMatch.type == .button && snapshotMatch.key == "privacySupport.entry")
  }
 }
 func require(_ condition: Bool, app: App, _ message: String) throws {
  events.append("require-free")
  precondition(message == "Requires an unentitled Free fixture; do not reset StoreKit automatically")
  guard condition else { throw Failure.rejected }
 }
 func attach(_ app: App, name: String) { events.append("attach-free") }
 func exercise() async throws {
'''+admission+'''
 }
}
@main struct Runner {
 @MainActor static func main() async {
  var count = 0
  for mode in ["lazy-free", "visible", "missing-free", "nonhittable-free", "scroll-fails"] {
   let harness = Harness(mode)
   var passed = false
   do { try await harness.exercise(); passed = true } catch {}
   let expected = mode == "visible" || mode == "lazy-free"
   guard passed == expected else { print("FAIL result \\(mode): \\(harness.events)"); exit(1) }
   let expectedEvents = expected ? ["free-down", "require-free", "attach-free", "entry-up"]
       : mode == "scroll-fails" ? ["free-down"] : ["free-down", "require-free"]
   guard harness.events == expectedEvents else { print("FAIL ordering \\(mode): \\(harness.events)"); exit(1) }
   count += 1
  }
  print("PASS \\(count) actual fixture-admission scenarios; native app calls=0")
 }
}
'''
with tempfile.TemporaryDirectory(prefix='tripdocket-fixture-admission-') as tmp:
    swift = Path(tmp) / 'admission.swift'
    binary = Path(tmp) / 'admission'
    swift.write_text(fixture)
    subprocess.run(['xcrun', 'swiftc', '-swift-version', '6',
                    '-strict-concurrency=complete', '-parse-as-library',
                    str(swift), '-o', str(binary)], check=True, timeout=90)
    subprocess.run([str(binary)], check=True, timeout=30)
