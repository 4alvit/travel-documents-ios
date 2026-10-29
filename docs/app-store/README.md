# App Store materials — English and Russian

Prepared 24 October 2026 (America/Los_Angeles) against application source
`0e669da95eb4d241d2141c1456a94d4f9d91ae25`. These are reviewed drafts and
screenshot candidates, not evidence of an App Store release or live purchases.
The accepted development preview remains the package built from that source.
Documentation and image additions do not create a new app binary.

## Copy fields

- Listing: [English](listing-en-US.json) · [Russian](listing-ru.json).
- One-time Pro: [localizations and setup](iap-localizations.json).
- App Review notes: [English](app-review-notes-en-US.txt) · [Russian](app-review-notes-ru.txt).
- IAP review notes: [English](iap-review-notes-en-US.txt) · [Russian](iap-review-notes-ru.txt).

JSON files are authoring records, not App Store Connect API payloads. Paste
only the corresponding field values. Use one language of review notes; do not
concatenate the English and Russian alternatives into the same field.

[Validation](validation.json) independently confirms all 18 limited fields:
name/subtitle 30 characters, promo 170, description 4,000, keywords **100 UTF-8
bytes**, App Review notes **4,000 UTF-8 bytes**, IAP name 30 and description 45.
[Apple references and units](apple-field-rules.json) explain the chosen limits.
Final App Store Connect validation remains required.

## Policy and support drafts

- Privacy: [English](drafts/privacy-en-US.md) · [Russian](drafts/privacy-ru.md).
- Support: [English](drafts/support-en-US.md) · [Russian](drafts/support-ru.md).

These public source drafts expose no customer information. Their bracketed
owner/contact/retention/effective-date fields are deliberately incomplete.
They are **not final privacy/support pages for submission**. Public access to a
commit-pinned draft proves only that the reviewed text can be read; it does not
satisfy every App Store policy or support requirement. Settings now includes
free bundled EN/RU guidance and explicit, confirmed links to published preview
documents pinned to commit `1391b30776cd6ea48eab97cd92d4b098ff8f9474`.
The guidance itself needs no network; opening a website does.

[Owner inputs](owner-inputs.json) separates unknown legal/contact facts from
technical work. The Free + one-time Pro model, target USD24.99, primary en-US,
Travel category and manual release are working defaults already recorded for
this preparation. The target price is currently a local test configuration,
not a live storefront price. Consumer copy uses the localized store price.

Before submission, fill actual owner/contact details, finalize and publish the
pages, replace the in-app preview links with those final URLs, check name availability, finish
Apple account/signing/product setup, review all privacy and legal declarations,
and complete physical-device QA. An IAP review image must depict the actual
configured product; old local-price paywalls are not evidence of live pricing.

## Screenshot candidates

See [screenshot evidence](../screenshots/README.md). Only current TripDocket
branding and synthetic documents belong in the candidate set. No old Tripfolio
branding, local-price paywall, simulator error screen or clipped notice is a
store-ready marketing image. Each retained image needs actual pixel dimensions,
language, runtime, source/binary provenance and independent visual review.
