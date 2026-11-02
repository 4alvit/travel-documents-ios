# Xcode 16.4 producer API evidence

Captured without native tests by diagnostic run [41371053226](https://github.com/4alvit/travel-documents-ios/actions/runs/41371053226), job 125041448908, on Xcode 16.4 build 16F6, SDK 18.5. Artifact 13109457168: 1968 bytes, SHA-256 `d1ce45bf24f71de1b9a99cd7036356d443216009e5224cd7e6f1209d507df7b9`.

`xcresulttool version` returned the retained exact version. Both `xcresulttool get test-results summary --schema` and `tests --schema` returned 64 with empty stdout and the retained stderr. These are unsupported-API observations, not schema documents. Empty stdout files are deliberately not used as schema fixtures. Native capture must retain strict actual result checks and mandatory independent Xcode 27.1 review.
