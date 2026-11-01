# App Store screenshot candidates

Captured 24 October 2026 (America/Los_Angeles), 25 October UTC. Application
source: `0e669da95eb4d241d2141c1456a94d4f9d91ae25`. These are **unedited raw
screenshots** from a separately rebuilt Debug QA app with unchanged production
sources, not a new build of the accepted Release preview package.

Four bounded UI capture cases passed, one for each device/language combination.
Each used normal simulated Face ID with one matching event and no application
authentication bypass. There was no purchase, test-price paywall or recipient
selection. All documents and people are fictional. The debug-only demo fixture
is not a feature offered in the release app.

- iPhone 17 Pro: 1206 × 2622, English and Russian.
- iPad Pro 13-inch (M5): 2064 × 2752, English and Russian.
- iOS 27.0 (24A434); Xcode 27.1; portrait; PNG RGB without transparency.
- Source/binary identities, image SHA-256 and individual case facts: [manifest](manifest.json).

The formats match Apple's currently listed [screenshot dimensions](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/).
Actual upload validation remains pending. These images do not prove physical
Face ID, production purchases, notification delivery or App Store approval.
Both temporary simulators were cleaned up after the capture batch.

Home and original-readiness are primary candidates. Original-preview is an
optional third image, showing a clearly marked training document. The iPhone
readiness screen scrolls: the lower recovery paragraph continues below the
floating tabs, so this frame is not a complete explanation of recovery.
On iPad the native toolbar truncates the search placeholder; document contents
and readiness controls remain visible. The iPad system status bar remains in
English even in the Russian app captures; the app interface, date formats and
original-document text use Russian. Persisted fictional names remain English
in the Russian UI by design.

## iPhone 17 Pro — English

- [Trips / Поездки](iphone-01-trips-en-US.png)
- [Original readiness / Проверка оригинала](iphone-02-original-readiness-en-US.png)
- [Original preview / Оригинал](iphone-03-original-preview-en-US.png)

## iPhone 17 Pro — Русский

- [Trips / Поездки](iphone-01-trips-ru-RU.png)
- [Original readiness / Проверка оригинала](iphone-02-original-readiness-ru-RU.png)
- [Original preview / Оригинал](iphone-03-original-preview-ru-RU.png)

## iPad Pro 13-inch — English

- [Trips / Поездки](ipad13-01-trips-en-US.png)
- [Original readiness / Проверка оригинала](ipad13-02-original-readiness-en-US.png)
- [Original preview / Оригинал](ipad13-03-original-preview-en-US.png)

## iPad Pro 13-inch — Русский

- [Trips / Поездки](ipad13-01-trips-ru-RU.png)
- [Original readiness / Проверка оригинала](ipad13-02-original-readiness-ru-RU.png)
- [Original preview / Оригинал](ipad13-03-original-preview-ru-RU.png)
