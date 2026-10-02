# absence-gate

[![ci](https://github.com/jbisaccia-9/absence-gate/actions/workflows/ci.yml/badge.svg)](https://github.com/jbisaccia-9/absence-gate/actions/workflows/ci.yml)

**A weekly check-then-chase job where a page that didn't load is never read as a document that isn't there.**

Plenty of operations work has this shape: a tracker of a few hundred records,
each of which must keep one time-limited document current in a third-party
system that has no API, files things inconsistently, and sometimes simply
doesn't answer. Once a week, someone works out who is due, looks each one up,
fixes the tracker when the document is already there, and emails the right
person when it isn't. Automating it is easy. Automating it so that it never
emails someone about a document they already uploaded is the actual job — and
the most common way to get that wrong is to treat a timeout, an unfamiliar
screen or an ambiguous search result as "not on file."

This repo is that job plus the gate that grades every run. Over a nine-week
synthetic season with a portal outage, a failure streak and flaky pages, the
run **held 47 lookups instead of guessing — and in 18 of them the certificate
was actually there.** A job that read "didn't load" as "not there" would have
sent every one of those 18 a notice. This one sent none, every week passed the
gate, and **7/7 counterexamples are refused, each for exactly the rule in its
name.**

## Quickstart

```bash
pip install git+https://github.com/jbisaccia-9/absence-gate
python -m absencegate season data                      # seed, then nine weeks: run live, grade, send
python -m absencegate seed dry && python -m absencegate run dry --week 1 --out out/dry   # DRY RUN: the default
python -m absencegate send out/dry                     # REFUSED G7: a dry run's outbox is never sent
python -m absencegate counterexamples out/cx && python -m absencegate check-dir out/cx --send   # exit 1
```

No credentials, no network, no model. The portal is a local mock; the login
reads two environment variable names (`PORTAL_USER`, `PORTAL_OTP_SEED`) and
never their values.

## The setting

Corvane Property Services (fictional) keeps a tracker of contracted vendors on
two boards. Every vendor must keep a current certificate of insurance on the
Tallgrass Vendor Exchange (also fictional, and deliberately unhelpful): it
stores IDs in a different format from the tracker, interrupts some records with
a prompt, labels the same document four different ways, keeps request forms and
sample certificates next to real ones, splits a record's documents across
pages, and times out — on the first page or the second.

Each week the job:

1. reads the tracker, finding columns by **title** (the same field has a
   different internal id on each board) and reducing each vendor to its current
   cycle;
2. skips closed, archived and exempt rows; marks the rest due if the
   certificate expires within 45 days, already has, or the date is missing or
   unreadable;
3. logs in once, then for each due row searches by ID, falls back to an exact
   name with exactly one result, opens the record and reads **every page** of
   the document list;
4. recognises a certificate by exact label only (type, then notes, then file
   name), always refuses known look-alikes, and hands anything *close* to a
   document reader;
5. writes found expiries back, records closures, and queues notices for the
   rest — up to six per vendor, at most one a week, re-checking the portal
   before every one;
6. writes the outbox, a row-by-row report and a summary, and exits. **The
   worker never sends mail.** The orchestrator does, once per notice, from a
   send log.

## Every row gets exactly one outcome

| finding | outcome | tracker | notice |
|---|---|---|---|
| exact certificate, date makes a later expiry | `ON_FILE` | expiry, on-file box, dated note | no |
| closure notice newer than any certificate, nothing says it's active again | `CLOSED` | status | no |
| looked, page loaded, nothing current | `NO_DOCUMENT` | — | yes, numbered from the ledger |
| same, but new threads are over this week's cap | `DEFERRED` | — | next week |
| no match, two matches, ID mismatch, no contact, ceiling reached, reader involved | `UNCLEAR` | — | **no — a person** |
| timeout on any page, unrecognised page, portal down, failure streak | `HELD`, naming the step | — | **no — unknown is not absent** |

## The document reader advises; rules decide

When the listing can't settle a record — a label like "cert of ins", or an
exact label with no date — a small LLM reads the document and returns
`is_target_document`, `effective_date`, `confidence` and `evidence`. The answer
is used only if it parses, clears 0.85, its evidence quote appears
**verbatim** in the document, and that quote states the date it gives. Even
then the reader can put a date on the tracker but can never close a record or
cause a notice: any record it touched that doesn't end `ON_FILE` goes to a
person. Answers in this repo are recorded, so CI needs no key; a live reader
sits behind the same `validate()`.

## The gate

`gate.py` grades a finished run directory against the inputs it started from
and **the portal's own action log** — not the worker's account of what it did.

| rule | what it refuses |
|---|---|
| G1 coverage | a current-cycle row with zero or two outcomes; a skip or not-due the tracker doesn't support; work on a row that wasn't due |
| G2 evidence | a tracker write that doesn't trace to a document this vendor's record really showed this week: an exact label with that date, or a reader answer that re-validates against the document text. An expiry that isn't effective date + validity, or that moves a date earlier. A closure the tracker or portal contradicts |
| G3 look first | any notice in a held run; a notice whose documents page didn't load, or that read fewer pages than the portal served; a notice where the reader was involved; a notice while a current certificate — or anything that might be one and was never read — was on file |
| G4 cadence | two notices to one row; a notice number that isn't ledger + 1; a notice past six; more new threads than the cap; anyone but this row's contacts on the message; another vendor's ID in it |
| G5 read-only | any portal action outside the allow-list (upload, delete and edit are tripwires); typing anything but a tracked vendor's ID or name, into anything but the search box |
| G6 clean reports | a vendor name, vendor ID or email address in the report or the summary that goes to the owners — they carry links and reason codes only |
| G7 once | (send mode) sending a dry run; sending a notice the send log already holds |

## The gate had a hole, and the first season found it

The first full season passed every week. Breaking the outcomes down per
scenario showed one that shouldn't have: a vendor whose certificate was listed
as **"cert of ins"** was getting weekly notices. The label check looked for
"insur", so the document was never recognised, never sent to the reader, and
the vendor was treated as having nothing on file. G3 passed it because G3 only
looked for exact labels.

Both halves are fixed. The worker now routes near-miss labels to the reader,
and G3 refuses a notice while *anything that might be the certificate* sat
unread. `test_an_unread_near_miss_label_cannot_produce_a_notice` reinstates the
old label check and asserts G3 now catches it. A season of green weeks was
evidence about the scenarios I'd thought to look at, not about the job.

## Lessons from a real build, and where each one lives

Each of these is a lesson from building this kind of job for real. Here every
one became a test rather than a paragraph:

| lesson | where it's enforced |
|---|---|
| Mark a message sent only after it is sent | `orchestrator.deliver` can fail mid-run; the log holds only what was delivered, and `send --resume` finishes the rest — `test_lesson_mark_sent_only_after_it_is_sent` |
| The dry run must apply the same caps as the live run | a dry and a live week 1 produce byte-identical reports, writes and outboxes — `test_lesson_dry_run_applies_the_same_caps_as_live` |
| Older portals are rarely one page | documents are paginated; a worker that reads only page one fails G3 — `test_lesson_older_portals_are_rarely_one_page` |
| Name every step and fail with a description | every held row names its step (`documents_page_2`, `record_page`), and errors describe what the page showed, never the record — `test_lesson_every_failure_names_its_step` |
| Business rules arrive from spot checks | a vendor closed last cycle and reopened this one is seeded, and must not be closed again — `test_lesson_a_record_that_closed_and_reopened_is_not_closed_again` |
| A contract between worker and orchestrator | the files the worker writes carry every field the orchestrator and gate read — `test_contract_worker_files_are_what_the_orchestrator_and_gate_read` |
| Keep a list of everything that uses each key | operational, not code: the only secrets are the two env var *names* in `worker.SETTINGS`, in one place |

## The counterexamples

```
g1-dropped-row             a row that needed a person silently left out of the report
g2-ungrounded-date         the reader's date accepted although its quote is not in the document
g3-timeout-as-absent       the documents page timed out; the run recorded 'no document' and queued a notice
g4-past-the-ceiling        the ledger shows six notices already; a seventh was queued anyway
g5-clicked-upload          the browser code touched an upload control on the portal
g6-name-in-summary         a vendor's name added to the summary that goes to the owners
g7-resend                  a timeout after delivery; the retry would send the same notice again
```

Each is a real week-2 run changed in exactly one way. CI requires
`check-dir --send` on that directory to exit non-zero, and a parametrized test
asserts each fails on its own rule and no other.

## Safety rails, and where each one lives

- **Dry run is the default.** Nothing is written or sent without `--live`, and
  the orchestrator refuses a dry run's outbox (G7).
- **No look, no notice.** Portal unreachable at login holds the whole run and
  emails nobody (week 4 of the season).
- **Stop after four failures in a row** rather than grinding through every
  record against a broken page (week 6).
- **Caps limit new threads, never checks.** Every due row is still looked up and
  its tracker updated; only first notices over the cap wait a week.
- **Read-only, enforced from the other side.** The portal mock refuses and logs
  anything not allow-listed, and the gate reads that log.
- **Exactly once.** The send log is written after every message. A plain retry
  of a run the log has already touched is refused (G7); `send --resume` is the
  deliberate way to finish an interrupted run, and it skips everything the log
  holds, so a crash at notice 4 of 10 sends 4 through 10 and nothing twice.

## What's here

```
src/absencegate/
  tracker.py          boards, columns by title, current cycle, applying writes
  portal.py           the mock portal: allow-list, tripwires, its own action log
  reader.py           recorded reader answers and validate()
  worker.py           decide, look, act; writes report, writes, outbox, summary
  orchestrator.py     re-grade with G7, send each notice once, update the ledger
  gate.py             G1-G7
  season.py           nine weeks end to end, scored against what the portal really held
  counterexamples.py  the seven runs that must be refused
  seed.py             the synthetic world
```

## Scope, stated honestly

- **Everything is fictional**: the company, the portal, every vendor, person,
  address and document. The portal's bad habits are seeded on purpose and
  each case says so in `seed.py`.
- The browser layer is a mock with the same shape as a headless-browser
  session (log in, type, click, read). Driving a real site means writing that
  layer against its real pages; the allow-list, the action log and the gate
  don't change. Check the site's terms of use before automating it.
- Reader answers are recorded. That proves the validation logic, not a model's
  accuracy; a live deployment needs its own labelled extraction set, scored on
  date accuracy and on refusing look-alikes, run several times per prompt
  change.
- The repo covers the first rungs of a sensible test ladder: unit tests against
  fake systems, browser code against a mock portal with tripwires, and an
  extraction check. The rest — a dry run against the real systems, a test
  send to yourself, one fake record end to end, an owner-reviewed preview,
  then go live — happen in a deployment, not a repo.
- Replies from vendors ("already uploaded", "wrong contact") are out of scope.
  The notice invites a reply and promises a re-check, and the next week's run
  re-checks regardless.
- G3's "was anything there?" check reads the portal fixture, which a real gate
  wouldn't have. In production that rule rests on the portal's action log
  alone: the page loaded, and the run says what it saw.

## Part of the *-gate* family

Nothing ships until it passes a gate — and the gate itself must be earned.
The others: [github.com/jbisaccia-9](https://github.com/jbisaccia-9).

MIT.
