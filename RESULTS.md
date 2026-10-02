# Results

Generated 2026-10-02 by `scripts/make_results.py` — every block below is captured command output, not prose.

## Unit tests

`python -m pytest -q` — exit 0, OK

```
.............................                                            [100%]
29 passed in 1.64s
```

## The season: nine weekly runs, each live, graded, then sent

`python -m absencegate season data --out out/season` — exit 0, OK

```
week   SKIPPED   NOT_DUE   ON_FILE    CLOSED  NO_DOCUM  DEFERRED   UNCLEAR      HELD   sent  gate
   1         8        46        16         2        10         3         5         5     10  PASS
   2        10        62         3         0        11         0         5         4     11  PASS
   3        10        65         5         0         9         0         5         1      9  PASS
   4        10        68         0         0         0         0         0        17      0  PASS   held: portal_unreachable
   5        10        68         2         0         9         0         5         1      9  PASS
   6        10        69         0         0         0         0         0        16      0  PASS
   7        10        69         0         0        10         0         5         1     10  PASS
   8        10        68         0         0        11         0         5         1     11  PASS
   9        10        68         0         0         7         0         9         1      7  PASS

held lookups across the season: 47
  of which the portal actually had a certificate: 18
  (a job that treats 'didn't load' as 'not there' would have sent each of those a notice)
```

## A dry run (the default)

`python -m absencegate seed dry && python -m absencegate run dry --week 1 --out out/dry` — exit 0, OK

```
wrote dry
# Week 1 (2026-10-05) - DRY RUN

SKIPPED 8 | NOT_DUE 46 | ON_FILE 16 | CLOSED 2 | NO_DOCUMENT 10 | DEFERRED 3 | UNCLEAR 5 | HELD 5

## For a person

- tracker://east/r0078 UNCLEAR reader:evidence_not_in_document
- tracker://east/r0085 UNCLEAR multiple_matches
- tracker://east/r0087 UNCLEAR missing_contact
- tracker://east/r0089 HELD timeout
- tracker://east/r0092 HELD page_unrecognised
- tracker://west/r0068 DEFERRED new_thread_cap
- tracker://west/r0071 DEFERRED new_thread_cap
- tracker://west/r0073 DEFERRED new_thread_cap
- tracker://west/r0077 UNCLEAR reader:low_confidence
- tracker://west/r0086 UNCLEAR id_mismatch
- tracker://west/r0088 HELD timeout
- tracker://west/r0091 HELD timeout
- tracker://west/r0095 HELD timeout

## Changes a live run would make

- tracker://east/r0052 Certificate expires: 2026-09-19 -> 2027-09-21
- tracker://east/r0052 On file: (blank) -> yes
- tracker://east/r0054 Certificate expires: (blank) -> 2027-10-01
- tracker://east/r0054 On file: (blank) -> yes
- tracker://east/r0056 Certificate expires: 2026-09-06 -> 2027-09-26
- tracker://east/r0056 On file: (blank) -> yes
- tracker://east/r0058 Certificate expires: 2026-08-29 -> 2027-10-03
- tracker://east/r0058 On file: (blank) -> yes
- tracker://east/r0061 Certificate expires: 2026-10-02 -> 2027-09-29
- tracker://east/r0061 On file: (blank) -> yes
- tracker://east/r0076 Certificate expires: 2026-10-28 -> 2027-09-17
- tracker://east/r0076 On file: (blank) -> yes
- tracker://east/r0081 Status: Active -> Closed
- tracker://east/r0083 Certificate expires: (blank) -> 2027-10-02
- tracker://east/r0083 On file: (blank) -> yes
- tracker://east/r0094 Certificate expires: 2026-09-13 -> 2027-10-01
- tracker://east/r0094 On file: (blank) -> yes
- tracker://west/r0053 Certificate expires: 2026-09-21 -> 2027-09-29
- tracker://west/r0053 On file: (blank) -> yes
- tracker://west/r0055 Certificate expires: 2026-09-01 -> 2027-09-21
- tracker://west/r0055 On file: (blank) -> yes
- tracker://west/r0057 Certificate expires: 2026-10-16 -> 2027-09-20
- tracker://west/r0057 On file: (blank) -> yes
- tracker://west/r0059 Certificate expires: 2026-11-11 -> 2027-09-25
- tracker://west/r0059 On file: (blank) -> yes
- tracker://west/r0075 Certificate expires: (blank) -> 2027-09-24
- tracker://west/r0075 On file: (blank) -> yes
- tracker://west/r0079 Certificate expires: (blank) -> 2027-09-29
- tracker://west/r0079 On file: (blank) -> yes
- tracker://west/r0082 Status: Active -> Closed
- tracker://west/r0084 Certificate expires: 2026-10-01 -> 2027-09-18
- tracker://west/r0084 On file: (blank) -> yes
- tracker://west/r0093 Certificate expires: 2026-10-25 -> 2027-10-01
- tracker://west/r0093 On file: (blank) -> yes

PASS     dry
```

## A dry run's outbox can never be sent

`python -m absencegate send out/dry` — expected non-zero exit, OK

```
REFUSED  dry                          G7  this is a dry run; its outbox is never sent
```

## Build the counterexamples

`python -m absencegate counterexamples out/cx --data out/cx-data` — exit 0, OK

```
g1-dropped-row             a row that needed a person silently left out of the report
g2-ungrounded-date         the reader's date accepted although its quote is not in the document
g3-timeout-as-absent       the documents page timed out; the run recorded 'no document' and queued a notice
g4-past-the-ceiling        the ledger shows six notices already; a seventh was queued anyway
g5-clicked-upload          the browser code touched an upload control on the portal
g6-name-in-summary         a vendor's name added to the summary that goes to the owners
g7-resend                  a timeout after delivery; the retry would send the same notice again
```

## Gate refuses every counterexample, each for its own rule

`python -m absencegate check-dir out/cx --send` — expected non-zero exit, OK

```
REFUSED  g1-dropped-row               G1  tracker://east/r0078: 0 outcomes, expected exactly one
REFUSED  g2-ungrounded-date           G2  tracker://east/r0078: reader date for D50910 is not grounded (evidence_not_in_document)
REFUSED  g3-timeout-as-absent         G3  tracker://east/r0089: notice queued but the documents page did not load (timeout) - unknown, not absent
REFUSED  g4-past-the-ceiling          G4  tracker://east/r0065: notice 7 is past the ceiling of 6
REFUSED  g5-clicked-upload            G5  portal action 'doc:upload' on 'file-input' is not allow-listed
REFUSED  g6-name-in-summary           G6  summary.md carries record details (1 value(s))
REFUSED  g7-resend                    G7  tracker://east/r0065: notice 2 for week 2 was already sent

0 pass, 7 refused
```
