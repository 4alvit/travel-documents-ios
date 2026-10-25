# Contributing

Open a focused pull request describing the user-visible behavior and validation.
Use only synthetic documents and people. Changes to import, persistence, export,
restore, authentication or purchases require regression tests and review of the
corresponding data boundary. Do not weaken quotas, authentication or CI to make
a test pass. Do not log OCR text, file contents, original names or store receipts.

Run `scripts/verify.sh`. UI changes should include simulator evidence, with
device/OS and commit recorded. Code contributions are licensed under MIT.
