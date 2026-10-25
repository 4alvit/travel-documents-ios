# TripDocket product scope and backlog

The first task is a complete offline travel-document workflow. People and trips
organize originals; human-confirmed dates support local reminders; an integrity
check and portable recovery let users prepare before leaving connectivity.

## Preview acceptance

- [x] Generic iOS Simulator Debug/build-for-testing and Release builds verified.
- [x] Core 38-test run and integrated 71-test run passed: AppModel/batch 35,
      reminder lifecycle/date 26 and localization 10. Denied cache cleanup
      preserves library access.
- [x] Actual Files batch import, individual review, changed-title reconfirmation,
      persistence and complete-original hashes verified on a configured iPhone Simulator.
- [x] Three selected UI scenarios pass on iPhone and iPad Simulators; captures reviewed.
- [ ] Import and scan a synthetic document, open original, verify offline.
- [ ] Reproducible cold-device StoreKit gate passes. Existing-device app/platform/UI
      suite passed 27/27; fresh iPhone/iPad probes failed during StoreKit setup.
- [ ] Full and selective packet recovery verified through the physical-device UI
      into a fresh installation; repository/AppModel recovery tests already pass.
- [ ] Corrupt/missing/oversized files and storage failures preserve existing data.
- [x] Five independent core/UI/platform review findings fixed and rechecked.
- [ ] Public repository CI green for the released commit.

Implemented scope includes editing trip names/departure dates, people and
document details; deleting a person retains unassigned documents, and deleting
a trip frees capacity for a new free trip. Civil dates retain their calendar day
across time zones. These features still require the physical-device checks in
[manual device QA](manual-device-test.md). See [release evidence](release-evidence.md)
for what has actually been executed.

## Languages

English and Russian follow iOS language preferences with English fallback.
Regional date/number formats and original document content remain independent.
The targeted simulator suite covers fallback, plurals, OCR and Russian layouts;
physical-device and notification-delivery checks remain in the release checklist.

## Batch import

Pro includes selecting up to 10 PDF/JPEG/PNG files in Files, reviewing each
original, and explicitly confirming its title, type, person and expiry choice.
Changing a confirmed detail requires confirmation again. One atomic save adds
the whole batch; an invalid file, cancelled preparation or failed save adds none.
The existing 16 MiB per-file and 64 MiB library limits still apply.

Preparation retains full bytes only in bounded RAM. The draft survives privacy
view teardown within the running process; quitting discards it. Preview copies
follow the protected temporary-cache lifecycle in data-and-recovery.md. A changed
library invalidates the draft; an unchanged refresh keeps it. Pro loss prevents
saving a batch without restricting viewing, editing, export or recovery of
existing documents. Runtime evidence and remaining device checks are recorded
separately in release-evidence.md.

## Later, after evidence

Additional languages,
export bundles in additional formats, measured limits for larger libraries,
accessibility testing on devices and more travel-document kinds. No automatic
sharing, email reading, cloud backend or claims of document/legal validity.
