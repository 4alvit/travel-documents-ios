# TripDocket data, export and recovery contract

## Local library

The repository actor is the single writer. A generation contains a catalog and
complete originals; an atomic pointer selects the current generation. A failed
import or restore must not publish a partially written library. iOS files and
directories use complete file protection. Standard device backup may include
the library according to the user's Apple settings; this is not our sync service.

Readiness verifies all bytes and SHA-256 against the imported original. Run it
again after changing files or restoring a device. It cannot validate passport
expiry rules, visas, bookings, or real-world sufficiency. Open each document too.

## Importing several files

The Pro batch flow accepts 1–10 selected PDF/JPEG/PNG originals. Every document
needs explicit confirmation of its title, type, person and expiry-date choice.
All prepared bytes remain in memory until Save; they are bounded by the remaining
64 MiB library capacity and 16 MiB per file. Process termination discards the
unsaved batch. A locked view can be recreated from the same in-memory draft.

Preparation failure or cancellation adds no documents. Saving validates and
publishes the complete batch as one generation; a failure or cancellation before
publication retains the old library. Cancellation after successful publication
does not reverse a completed save. Source files are never deleted. Prepared
previews use the same temporary-file lifecycle described below.

Pro is checked when starting, after asynchronous preparation and before save.
Loss of Pro leaves a prepared review available but prevents saving the batch.
Existing original access, editing, export and recovery do not depend on Pro.

## Export

`.tripbackup` is a bounded JSON container containing the selected catalog and
base64 originals. **Base64 is not encryption.** Packets are readable by recipients
and software with access to the destination. The share sheet opens only after a
user action and warning. There is no remote expiration or revocation.

A selection includes only its documents and referenced trips/people. Full backup
also includes empty trips and people. Temporary previews/exports use protected
cache files excluded from backup and are cleaned on the next launch. Copies
saved to Files or another app are outside TripDocket's control.

Temporary preview originals are removed when their preview closes while the
scene is active. A preview interrupted by backgrounding is left for later cache
cleanup because QuickLook may have started a share extension. Explicit share
copies are removed after the system activity reports completion or cancellation,
not merely when its view disappears. Abandoned copies are cleared before another
preview/export and on the next launch. Successful document/trip deletion and
replacement restore also clear this cache. Physical-device extension/background
behavior remains a pending manual check, not a guarantee established by unit tests.

Departure and expiry fields represent calendar days. The JSON Date value
encodes Gregorian year/month/day at 12:00 UTC, with `TravelDate` converting at the
UI boundary. Changing time zones does not change the confirmed day. Import and
readiness timestamps remain actual instants. This is the first, unpublished
format version; imported backups must use the same date convention.

## Restore

Restore replaces, rather than merges, the local library after explicit
confirmation. Save a backup first if both sets must be kept. Schema, references,
IDs, filenames, complete bytes, content types, checksums and limits are checked
before publication. A failed validation leaves the prior active library intact.

Limits: 16 MiB per original, 64 MiB total, 96 MiB encoded input, 1,000 entries per
catalog collection. A second installation can restore a selected packet without
the original device or an app account. Pro entitlement is independent of data:
restoring a large existing library is allowed without Pro, but new additions
over Free limits require an active verified Pro purchase.

Losing the device and all backups can lose the library. Restore Purchases restores
only the Pro license. It cannot recover files. Reminder schedules are device-local
and must be explicitly recreated after a replacement restore.
