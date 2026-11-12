# Historical scan

Set `HISTORY_START` and a fixed `HISTORY_END` (UTC, exclusive). The setup helper
fixes the end at setup time. The scan visits half-open monthly windows `[start,end)`
using `/me/messages`, `receivedDateTime` filters, ascending received time, selected
fields, and 100 items per page. Microsoft server cursors are opaque and must not be
reconstructed. All folders Graph exposes through this endpoint are in scope.

Each schedule execution claims one page with a ten-minute UUID lease. A concurrent
execution does no work while that lease is valid. The page and checkpoint commit
in one PostgreSQL transaction. A failed or interrupted request never advances the
checkpoint. After expiry another execution can reclaim it; the old token cannot
commit. The last page of a window advances the window, and the last window marks
the scan complete. A scheduler tick is bounded to one page to respect API limits
and allow live traffic to continue. Increase schedule frequency only after checking
tenant throttling and extraction backlog.

Messages deduplicate by mailbox plus Internet Message-ID, falling back to immutable
Graph ID. Alias rows preserve Graph IDs across overlapping imports. Content hashes
identify versions; old pages cannot replace a message with an older last-modified
timestamp. Separate emails with the same invoice reference, vendor name/domain,
direction, amount and currency share one invoice candidate with multiple evidence
rows. Unreferenced facts and payments do not merge across distinct source messages.
This intentionally favors review over falsely collapsing multiple payments.

`429` stores `Retry-After` seconds (bounded to one day; 60s fallback), `5xx` stores
a retry delay, and `401/403` remains an authorization error visible in sync health.
An expired live delta token (`410`) starts a deduplicated baseline again. Transport
failures leave a lease to expire. Inspect n8n execution status without retaining
mail data; API health cards show checkpoint errors and queue failures. Model errors
retry at most five times with backoff; review failed jobs before manually resetting
their attempt count. Error storage contains exception classes, not provider bodies.

Changing historical bounds does not rewrite an existing scan. For an intentional
rescan, deactivate its workflow, wait for in-flight work to finish, back up the
database, then delete only its `sync_state` row and reactivate. Retained messages
and facts will deduplicate. Do not clear message or evidence tables to rescan.

Graph is a live mailbox, not a point-in-time backup. A message moved/deleted before
its page is read may be absent; an Inbox delta removal may indicate a folder move.
Such removals flag locally known messages unavailable and exclude their current
facts from dashboards while preserving evidence. Initial full historical coverage
and ongoing Inbox coverage are displayed separately. Historical dates and ledger
payment completeness must never be inferred solely from sync completion.
