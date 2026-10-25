# TripDocket manual device QA — pending execution

**Status: no physical-device execution is recorded in this checklist.**
Prepared 20 October 2026. Every unchecked item is pending. A successful compiler
run, unit test, StoreKit configuration or simulator screenshot does not mark a
physical-device test complete.

Separate automated results are tracked in [release evidence](release-evidence.md):
Core 23 passed; an existing iPhone Simulator passed all 27 app/platform/UI tests,
including actual system purchase cancellation. Later AppModel 14/14, six normal
simulated-authentication privacy cases and selected maximum-type UI checks are
recorded separately. Fresh-device CLI StoreKit setup is still blocked. None of
these results checks off the physical-device items below.

Use synthetic documents and fictional people only. Backup replacement and
app deletion below are destructive test actions: use a dedicated test library
and device, never a person's working document collection.

## Evidence record

Complete one record per tested build/device combination:

- Commit SHA / branch: pending
- Build version / build number: pending
- Distribution and signing mode: pending
- Device model and capacity: pending
- iOS version / build: pending
- Date, tester and timezone: pending
- Device passcode and biometric configuration: pending
- StoreKit environment, product configuration and test account: pending
- Free capacity at start / constrained-storage method: pending
- Synthetic fixture hashes and locations: pending
- Result, issue links and evidence paths: pending

Keep logs and screenshots free of credentials, real documents and account
identifiers. Use explicit Pass / Fail / Blocked / Not applicable outcomes when
recording execution; do not convert a blocked case into a pass.

## First launch and authentication

- [ ] Fresh install with passcode configured: no document content is visible
      before device-owner authentication; successful Face ID, Touch ID or
      passcode authentication opens the library.
- [ ] No device passcode: the app stays locked and explains that a passcode
      is needed. Configure a passcode and confirm recovery without app deletion.
- [ ] Fail biometric authentication, cancel the prompt and use passcode fallback.
      Failed/cancelled attempts reveal no document content and allow retry.
- [ ] Trigger biometric lockout where feasible; verify system fallback and a
      clear locked state. Record the actual tested authentication path.
- [ ] Background during authentication, then foreground: a late response cannot
      expose documents without a valid current unlock. Repeat after a failed
      attempt and after locking the device.
- [ ] Settings > Lock now immediately hides content and requires authentication
      again. It must not erase documents or silently disable the passcode gate.

## Privacy while other screens are presented

For **each** surface below, show synthetic content, enter the app switcher,
background, lock the device, and return. Record app-switcher and screen evidence.
The TripDocket snapshot must be covered; document content must stay inaccessible
until the current unlock succeeds. Check that the return path does not strand
the user behind an undismissable sheet or lose a confirmed import/purchase.

- [ ] Trip detail and document edit form.
- [ ] Change title, type, person and expiry without saving; background and lock
      the device, then authenticate. The draft must return intact while the same
      process is running. Save and verify unchanged original bytes. Repeat with
      Cancel; an unsaved draft is not promised to survive process termination.
- [ ] Files import picker, including a selected file/provider preview.
- [ ] QuickLook original preview, including page navigation.
- [ ] System share sheet after an export warning, including destination picker.
- [ ] Restore file picker and replacement confirmation.
- [ ] Camera scanner and its page-review screen.
- [ ] StoreKit purchase confirmation and Restore purchases authentication.
- [ ] Notification permission prompt initiated by an expiry-reminder action.
- [ ] Start a reminder, then delete/edit its document or restore a library while
      permission is pending. Resolving the old request must not restore a stale
      notification; a subsequent valid reminder must remain scheduled. Confirm
      actual delivery separately from controlled-client regression tests.

System interfaces can display files a user explicitly selected or chose to
share. Record those boundaries separately from TripDocket's own snapshot and
lock behavior; do not claim that the app can revoke or hide a recipient's copy.

## Trips, people and correction

- [ ] Create a trip with and without departure date; whitespace-only names are
      rejected without a partial entry. Edit the name and departure date.
- [ ] Add and rename people. Import documents assigned to a person and unassigned.
      Search by document title, person and type; clear search and recover the list.
- [ ] Edit a document's title, kind, person and confirmed expiry date. Reopen and
      relaunch to confirm persistence and unchanged original contents.
- [ ] Delete a person: confirmation says documents are retained and unassigned;
      confirm that the originals still open and verify.
- [ ] Delete a document: cancellation preserves it; confirmation removes it and
      its reminder, while an earlier exported copy remains unchanged.
- [ ] Delete a trip containing documents: warning gives the original count and
      recommends export first. Cancellation preserves everything; confirmation
      removes that trip's originals while retaining other trips and people.
- [ ] As a free user, delete the old trip and create another without being forced
      to buy Pro. Verify free limits of 1 trip, 2 people and 8 documents on additions.

## Import, camera and OCR

- [ ] Import synthetic PDF, JPEG and PNG from local Files; verify title, type,
      assigned person, confirmed date and full original rendering.
- [ ] Import a cloud-provider file that is downloaded, then one not downloaded
      while offline. The unavailable file produces a useful error and no phantom
      document or misleading ready status.
- [ ] Deny camera access, cancel scanning, and recover through system Settings.
      Existing documents remain available.
- [ ] On supported physical hardware, scan one and multiple pages, rotate/crop
      using the system controls, save, then open every PDF page. Verify clarity.
- [ ] Exercise the 25-page scan boundary and a scan exceeding 16 MB where feasible.
      Oversize input is rejected without a partial library entry or lost originals.
- [ ] Run optional OCR on clear and illegible synthetic text; edit the suggestion
      and choose its first line as title. Dates are never silently populated.
- [ ] Use a PDF longer than 3 pages; OCR copy makes the three-page recognition
      limit clear and importing preserves the entire PDF.
- [ ] Attempt an unsupported format, renamed invalid file, zero-byte file and a
      file over 16 MiB. Errors remain readable, existing data remains intact.
- [ ] Exceed 64 MiB of library originals through successive imports. The rejected
      addition does not damage earlier documents. Check UI responsiveness.

## Batch import with per-document confirmation

- [ ] With Pro, select two different originals in Files; neither appears in the
      library before Save. View both originals and confirm their title, type,
      person and expiry choice. Changing any confirmed detail requires fresh
      confirmation. Save once; both originals must appear and verify.
- [ ] Repeat with 10 files. Reject 11 without silently truncating the selection.
      Invalid or oversized files must leave no imported prefix.
- [ ] Cancel while a provider read is pending, then start another batch. A late
      result from the old selection must not replace the new draft or its progress.
- [ ] Background and authenticate with unsaved batch details. They must return
      in the same process. Separately force-quit and verify the documented loss
      of the unsaved draft, while previously saved originals remain intact.
- [ ] Revoke Pro during preparation and before Save. No batch is published;
      existing original access, editing, export and recovery remain available.
- [ ] Complete review at maximum Dynamic Type and with VoiceOver, including two
      source files with the same filename but different confirmed titles.

## Complete-original offline readiness

- [ ] Import multiple original formats, run Check all originals and note check
      time and per-file results. A new unchecked file must not inherit a verified
      status from an older file.
- [ ] Enable Airplane Mode and disable Wi-Fi, reboot the physical device, unlock
      it and the app, then verify and open **every complete original**, including
      the last page of a multipage PDF and full-resolution image contents.
- [ ] Repeat after force quitting and after the device remains locked for a period.
      Record connectivity and whether the original was fully readable each time.
- [ ] Verify the UI distinguishes last-check evidence from a guarantee of future
      availability; a thumbnail alone is never the acceptance evidence.
- [ ] In a controlled development test container, remove, alter and make an
      original unreadable one at a time. Confirm missing/changed/unreadable
      results and no false ready result; restore the synthetic fixture afterward.
- [ ] If controlled file mutation is unavailable on the signed device build,
      mark that device case blocked and link the separate repository test evidence.

## Explicit export and real recovery

- [ ] Export a selected packet: verify the unencrypted-content warning precedes
      the share sheet, cancellation sends nothing, and only selected originals
      plus their related trip/person details are in the packet.
- [ ] Keep an export or QuickLook share extension open while backgrounding the
      app. Confirm the source remains readable until the extension completes;
      verify subsequent cleanup without deleting library originals. Record both
      normal completion/cancellation and an interrupted extension.
- [ ] Export the full library to a trusted test destination. Record independent
      SHA-256 values of the synthetic original files before recovery.
- [ ] On another freshly installed test device or after intentionally deleting
      and reinstalling the test app, restore that exported backup. Confirm all
      trips, people, metadata and original bytes match; open every original.
- [ ] Repeat recovery without Pro to verify that recovery and existing-data
      access remain available even when the restored library exceeds free limits.
- [ ] Restore into a nonempty synthetic library: cancellation preserves the
      current library; confirmation replaces it rather than merging or duplicating.
- [ ] Reject truncated, corrupt, tampered, duplicate-entry and over-96-MiB backup
      inputs. Record that the complete pre-existing library is preserved.
- [ ] After successful replacement, old reminders are gone and the UI asks the
      user to schedule reminders again. No reminder is silently created by import.
- [ ] Uninstalling without a backup is not represented as recoverable through a
      TripDocket account. Verify the on-screen backup explanation is clear.

## Reminders

- [ ] In Pro, set a human-confirmed future expiry and explicitly schedule a
      reminder; verify the displayed confirmation and notification-permission flow.
- [ ] Denied permission produces actionable feedback without pretending success.
- [ ] Test dates more than 30 days away, inside the 30-day window, today and in
      the past. Verify 9 AM in the time zone used when scheduled, or a clear
      too-soon/expired rejection.
- [ ] Notification content does not reveal a person's name, document title,
      passport details or filename on the lock screen.
- [ ] Edit the document and confirm the previous reminder is cancelled. Enabling
      a new reminder requires another explicit user action.
- [ ] Change device timezone and confirm the scheduled reminder preserves the
      time zone used when scheduled; it must not move to 9 AM in the new zone.
      Verify that this behavior is explained before confirmation. Separately
      record actual Focus/notification-delivery behavior without assuming a
      delivery guarantee.
- [ ] Enter trip departure and document expiry dates, change between far-apart
      time zones, then view and edit them. Confirm the same calendar dates remain
      displayed and a no-change save does not shift them by a day.

## StoreKit and entitlement transitions

Use a configured StoreKit test session or an approved sandbox account and record
which environment produced each result. These tests do not demonstrate live sales.

- [ ] The paywall shows the StoreKit-localized currency/price; an unavailable
      product shows retry guidance and does not permit a misleading purchase.
- [ ] A verified successful non-consumable purchase unlocks Pro additions and
      reminders. Restart and confirm the entitlement is recognized.
- [ ] Cancel a purchase; free access and existing documents remain unchanged.
- [ ] Exercise Ask to Buy/pending, then approve and reject as the environment
      permits. Pending must not unlock Pro before a verified transaction.
- [ ] Exercise Restore purchases with a prior purchase, no prior purchase,
      cancellation and a network failure. Record the displayed results.
- [ ] Exercise refund/revocation. Pro additions become restricted, while viewing,
      metadata editing, deleting, basic export and backup recovery still work.
- [ ] After a verified purchase, restart offline; verify the behavior based on
      StoreKit's available local entitlement history. Failure to fetch a price
      must not independently hide or delete the existing library.
- [ ] Block purchases with device restrictions and verify actionable feedback.
- [ ] Unverified and delayed/out-of-order transactions need controlled test
      support. Record any device cases that are unavailable; link automated or
      isolated state tests separately rather than calling the device case passed.

## Interruptions, storage and accessibility

- [ ] With a nearly full dedicated test device, import, scan, export and restore
      fail gracefully when a write cannot complete. Existing originals remain
      readable and the next operation can succeed after space is freed.
- [ ] Interrupt import and restore at controlled points by backgrounding or
      terminating. On relaunch, the library is a valid old or completed new state,
      never a partly replaced catalog with missing old originals.
- [ ] Use the largest Accessibility Dynamic Type sizes, Bold Text and increased
      contrast. Main actions, notices, errors, prices and destructive warnings
      remain visible or scrollable; no clipped essential content.
- [ ] Navigate all tabs, forms, document actions, paywall and confirmations with
      VoiceOver. Labels describe actions; selection and readiness are understandable
      without color; no focus trap or unlabeled actionable icon.
- [ ] Test iPhone portrait/landscape and iPad resizing/rotation. Menus, pickers,
      QuickLook and share sheets are anchored, dismissible and usable.
- [ ] Test empty library, no search results, working/loading and operation errors.
      Repeated taps cannot create duplicate entries or misleading success notices.

## Exit gate

Before marking a release candidate ready, attach the completed execution records,
fix and retest blocking failures, and link the separate unit-test, build, review
and published-commit CI evidence. Keep unsupported hardware paths and unexecuted
cases explicitly pending. This document alone is not an approval to publish.
