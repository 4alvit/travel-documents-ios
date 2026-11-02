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
