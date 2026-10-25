# Simulator screenshots

These are unedited XCUITest captures of the development preview, using only
fictional trips, people and generated documents. They are review evidence,
not an App Store submission or proof of physical-device authentication.

## Current App Store candidates

The reviewed [English/Russian iPhone and 13-inch iPad set](app-store/README.md)
uses application source `0e669da95eb4d241d2141c1456a94d4f9d91ae25`.
It includes no paywall or local test price. See its manifest for raw image hashes,
device dimensions, source and rebuilt Debug binary identities.

## Earlier TripDocket evidence

Source `f3b56885a1bd7ae721764389a2a7490778d5a31b`, existing iPhone 17 Pro
Simulator, iOS 27.0 (24A434), 21 October 2026. All three selected nonpayment
UI tests passed in `build/TripDocketBrandUI.xcresult`; captures were visually
checked. No purchase was attempted. The $24.99 displayed on the Pro screen
comes from the local Xcode test catalog, not a configured live App Store price.

- [TripDocket iPhone original readiness](tripdocket-iphone-original-readiness.png)
- [TripDocket iPhone locked interface](tripdocket-iphone-locked.png)
- [TripDocket iPhone Pro screen](tripdocket-iphone-pro.png)

## Historical Tripfolio brand

The following captures retain the prior brand and their original evidence.
The Pro screen comes from the passing existing-device full run, source
`17025401b1958266ba5e5eb4273a80d83dbd2a27`. Corrected iPhone readiness/lock
captures use `a14974554de95606a504caec8a691203d9ba2c1f`; corrected iPad captures
use `42bf9fcebda6516a0fee003fc6fecf0fa0465d63`. Their results and environment
limitations remain in [release evidence](../release-evidence.md).

- [Tripfolio iPhone original readiness](iphone-original-readiness.png)
- [Tripfolio iPhone locked interface](iphone-locked.png)
- [Tripfolio iPhone Pro purchase screen](iphone-pro.png)
- [Tripfolio iPad original readiness](ipad-original-readiness.png)
- [Tripfolio iPad locked interface](ipad-locked.png)

The lists scroll; partially visible content at the screen edge is not clipped
out of the document. The lock captures demonstrate removal of the document
interface only. Physical biometric/passcode and app-switcher checks remain
separate release requirements.
