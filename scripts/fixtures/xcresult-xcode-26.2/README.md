# Xcode 26.2 schema documentation

These are the unmodified `xcresulttool get test-results summary --schema` and
`tests --schema` outputs from Xcode 26.2, build 17C52, retained in
[CI 41352317506, artifact 13100939614](https://github.com/4alvit/travel-documents-ios/actions/runs/41352317506/artifacts/13100939614).
They contain API metadata, not application or user data.

The summary documentation is intentionally stored as `.txt`: its producer
emits invalid JSON. Tests recognize the exact original bytes and reject changed
documents; they do not repair or relax parsing of actual execution results.

- `summary-schema.txt`: SHA-256 `caebdac65d3702246017a340212ddf224723bb24db65631c47ff08bf140a5e66`
- `tests-schema.json`: SHA-256 `e2ab685a13f16c60c44bec331e90c85973f0e3cc1fcd9669ddee541fc1ad3609`
