# BUILD_LOG convention

`BUILD_LOG.md` is the session-by-session record of how this product was built.
It exists so that any result can be traced back to the decisions and data that
produced it — especially important for a screening product whose honesty
depends on documented uncertainty.

## Rules

1. **One entry per working session**, newest at the top, headed
   `## YYYY-MM-DD — short title`.
2. Every entry uses these sections (omit a section only if genuinely empty):
   - **Goal** — what this session set out to do.
   - **Decisions** — choices made and *why*, including rejected alternatives.
     Anything the user confirmed at a checkpoint is recorded here verbatim.
   - **Provenance** — every dataset touched: source, URL, version/date
     retrieved, licence, and any transformation applied.
   - **Residuals & caveats** — known weaknesses left in deliberately, honest
     statements of what this step does *not* establish. Never hide these.
   - **Checkpoints** — user review gates hit this session and their outcome.
   - **Next** — what the following session should pick up.
3. **Never rewrite history.** Corrections get a new dated entry that references
   the old one.
4. Numbers quoted in an entry (sizes, runtimes, percentiles, break values) must
   be measured, not estimated — or explicitly labelled as estimates.
5. Deviations from the original spec are logged the session they occur, with
   the reason and the user's sign-off status.
