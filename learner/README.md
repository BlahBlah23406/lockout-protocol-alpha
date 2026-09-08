# learner — turning "False alarm" presses into a policy

Experimental, self-contained, offline. Pure Python 3.12 standard library: no pip installs, no
network calls, no ML runtime. It reads the app's judgement log, learns from the feedback the user
gave on block screens, and writes one portable file — `focus_policy.json` — that the Windows
(Python), macOS (Swift) and Android (Kotlin) clients all read with nothing but a JSON parser.

## Why it exists

The focus monitor screenshots the foreground app every couple of minutes and asks a vision model
whether the screen is consistent with the task the user declared. Its dominant failure is the
**false alarm**: the model blocks a screen that was genuinely part of the work — a Khan Academy
lecture for "math test prep", r/learnmath, a study-group Discord, LinkedIn during a job hunt.

False alarms are not a cosmetic problem. Two or three in an afternoon and the user turns the
monitor off, at which point it protects nothing at all. This package consumes the "False alarm"
button and makes the same mistake less likely next time.

It is built on one empirical claim, and everything here fails if the claim is wrong: **the
model's errors are systematic, not random.** It does not misfire uniformly — it misfires on the
same handful of legitimate-support screens over and over. A random error has no signature to
learn.

---

## Running it

```bash
# from the repo root
python -m learner.cli simulate                                    # make labelled synthetic data
python -m learner.cli simulate --gamer --out learner/data/judgements_gamed.jsonl
python -m learner.cli learn                                       # -> learner/data/focus_policy.json
python -m learner.cli evaluate                                    # the scorecard
python -m learner.cli explain "studying for my math test" chrome.exe "Improper integrals - Khan Academy"
python -m unittest discover learner/tests                         # 71 tests
```

To feed the real app, point `learn --log` at the monitor's `judgements.jsonl` and `--out` at
`%LOCALAPPDATA%/Guardian/focus_policy.json`. The client picks it up on the next check; nothing
needs restarting.

| file | what it is |
|---|---|
| `store.py` | reads `judgements.jsonl`, folds feedback rows into their judgements, survives damage |
| `features.py` | model-free signals: task cluster, app, title pattern, domain, time bucket |
| `learn.py` | the three mechanisms **and the anti-gaming guard** |
| `policy.py` | compiles `focus_policy.json`; `apply()` is the reference client |
| `simulate.py` | labelled synthetic judgement streams, honest and adversarial |
| `evaluate.py` | before/after scorecard with ablations |
| `cli.py` | `simulate \| learn \| evaluate \| explain` |

---

## The data contract

The producer is `windows/guardian/models/judgements.py`. Append-only JSON Lines, never rewritten.
A judgement is one row:

```json
{"id": "j_1757300123400", "ts": 1757300123.4, "session_id": "fs_ab12",
 "task": "working on math test prep", "app": "chrome.exe", "app_name": "Chrome",
 "window_title": "Integration by parts - Khan Academy",
 "verdict": "off_task", "reason": "YouTube video page visible, unrelated to math",
 "confidence": 0.72, "action": "blocked", "provider": "ollama:qwen3-vl:8b",
 "feedback": null, "feedback_at": null, "feedback_note": null}
```

and pressing "False alarm" later appends a **separate** row pointing back at it, because
rewriting a line in place would mean rewriting the whole file while the monitor thread is
appending to it:

```json
{"id": "j_1757300123400#fb", "ts": 1757300140.0, "ref": "j_1757300123400",
 "feedback": "false_alarm", "feedback_at": 1757300140.0, "feedback_note": "this is my textbook's video"}
```

`store.read_judgements` folds the pair the way `judgements.read_all()` does. Folding is done over
the whole file, not streamed, because a feedback row can appear thousands of lines after its
target — or, once two logs are concatenated, before it.

- `verdict` ∈ `on_task` | `off_task` | `unreadable`
- `action` ∈ `blocked` | `logged` | `allowed`
- `feedback` ∈ `null` | `false_alarm` (wrong to flag) | `correct` (right to flag) | `missed`
  (should have flagged and didn't)

Unknown enum values fail closed (`verdict` → `unreadable`, `action` → `logged`), malformed lines
are skipped and counted, and feedback rows whose judgement has been trimmed off the front of the
log are reported as orphans rather than silently dropped.

---

## The three mechanisms

**(a) Exemplar memory.** The strongest confirmed false alarms become one-line sentences appended
to the classifier prompt, under the `PREVIOUSLY CONFIRMED BY THE USER — treat these as settled:`
heading that `ai/providers.build_user_prompt` already renders:

```
- Chrome showing khanacademy.org is part of this task (you confirmed 4 times).
- Discord showing discord.com is part of this task (you confirmed 6 times).
```

Phrased as settled facts, not instructions — the heading already carries the imperative, and a
second one just gives a small model something to argue with. The confirmation count is included
deliberately: it gives the model a reason to trust the line and a human an audit trail. Capped at
1200 characters and 8 lines, because every character is paid for on every check, hundreds of
times a session. Selection is two-stage: the compiler ranks by evidence × recency (21-day
half-life), and the client re-ranks by keyword overlap with the task the user actually typed, so
a user with four projects doesn't spend their whole budget on the other three.

**(b) Signature allowances.** A `(task-cluster, app, title-pattern)` triple confirmed repeatedly,
across separate days, becomes a pre-model decision:

- `pre_allow` — skip the check entirely. No screenshot sent, no model call, no block.
- `downgrade` — run the check, log it, but only block at the ceiling confidence.

This is the mechanism that actually removes interruptions, because it doesn't depend on a model
changing its mind. It is also the dangerous one, so it needs the most evidence and expires on its
own.

**(c) Confidence calibration.** A per-`(task-cluster, app)` block threshold:

```
threshold = 0.55 + 0.05 × credited_false_alarms − 0.10 × missed      clamped to [0.30, 0.85]
```

Linear rather than Bayesian on purpose. A Beta posterior would be defensible and a nightmare to
port and to explain to the person it is blocking; *"each false alarm you confirm moves the bar
five points, each miss moves it back ten"* is a sentence a user can hold in their head. The
asymmetry is the point: the user asked to be stopped, so the tool tightens twice as fast as it
loosens.

They compose in that order at apply time: an allowance short-circuits the check, otherwise the
threshold decides blocking, and the exemplars ride along on every prompt regardless.

---

## The anti-gaming design

**The user of a self-control tool is not a neutral labeller.** They are the person the tool exists
to stop, holding a button marked *"stop stopping me"*. Every loosening path is therefore rate
limited, capped, evidence-gated, expiring, and observable. Nine guards, all in `learn.py`:

| # | guard | rule |
|---|---|---|
| 1 | **rate limit** | at most 12 credited false alarms per rolling 24h; later presses are recorded but teach nothing |
| 2 | **reflex filter** | a press within 3s of the block isn't a considered judgement, it's a reflex |
| 3 | **per-signature cap** | one signature banks at most 6 credits — spamming the same block buys nothing past the sixth |
| 4 | **evidence spread** | an allowance needs 3 credits across ≥2 separate calendar days; one angry sitting unlocks nothing |
| 5 | **contradiction** | `correct` presses subtract from a signature's evidence; one `missed` revokes its allowance outright |
| 6 | **expiry** | allowances die 14 days after their last credited evidence — enforced at *apply* time too, so an un-recompiled policy still decays |
| 7 | **hard ceiling** | the threshold can never exceed 0.85. There is no sequence of button presses that turns blocking off |
| 8 | **never-pre-allow** | leisure-leaning domains (youtube, tiktok, instagram, netflix, twitch, twitter/x, facebook, pinterest, reddit, steam, amazon) reach `downgrade` at most, never a skipped check — so the session stays in the log and visible to the partner |
| 9 | **visibility** | `integrity` in the policy carries a gaming score and a ready-to-send sentence for ntfy |

Guard 9 is the one that matters most, because every mechanical limit above can eventually be
waited out. A weighted score over four rates — what fraction of blocks get dismissed, how many
presses land in under 3 seconds, how many hit a cap, how many argue with a *confident* verdict on
a leisure site — plus two hard trips. Over the alert line, the policy carries:

```json
"integrity": {"score": 1.0, "notify_partner": true,
  "headline": "Focus learning is being pushed hard: 80% of blocks are being marked a false alarm; 61% of presses came in under 3s; 74% of presses hit a rate limit or cap."}
```

The app pushes that to the accountability partner's ntfy topic. Learning being used to erode the
rules is itself reportable.

### Two guard numbers were wrong, and measurement caught them

The first version flagged the **honest** user (integrity 0.53, alert fired). Both causes were
real bugs, not tuning taste:

1. `max_credited_fa_per_day = 8` fired on an honest user *every day* — with a model this eager,
   ten genuine false alarms in a heavy session is normal. Raised to 12. A limit that routinely
   trips on the honest case is not a guard, it's noise, and it teaches everyone to ignore the
   alert.
2. Counting *every* press on a leisure domain as gaming flagged the honest user on 46% of their
   presses — because arguing "this YouTube page is my textbook's lecture" is the exact use case
   the product exists to serve. Now only presses against a **confident** (≥0.80) verdict on a
   leisure domain count. "YouTube at 0.62" is the Khan Academy lecture; "TikTok at 0.94" is
   someone telling the tool to look away.

After the fix: honest user scores 0.30, no alert. Spammer scores 1.00, alert fires.

---

## `focus_policy.json`

Versioned (`"schema": 1`) and refused wholesale by every client if the schema is unknown or
`generated_at` is more than 60 days old — a partially-understood policy is worse than none,
because the parts you drop might be the safety limits.

```jsonc
{
  "schema": 1,
  "generated_at": 1757300000.0,        // unix seconds; clients expire it after 60 days
  "generator": "learner/policy.py v1",
  "exemplar_count": 13,                // the client status line reads these two
  "signature_count": 11,

  "defaults": {
    "block_threshold": 0.0,            // "no opinion" — see the note below
    "calibration_base": 0.55,
    "threshold_floor": 0.30,
    "threshold_ceiling": 0.85,
    "cluster_match_threshold": 0.33,
    "exemplar_budget_chars": 1200,
    "exemplar_max_lines": 8
  },

  "clusters": [                        // freehand task strings, grouped
    {"id": "tc_07a3299c", "label": "math revision for the calculus exam",
     "keywords": ["calculu", "exam", "math", "prep", "revision", "study", "test"],
     "keyword_sets": [["calculu","exam","math","revision"], ["math","study","test"]],
     "tasks_seen": 3}
  ],

  "exemplars": [                       // mechanism (a) — ranked candidates, per cluster
    {"cluster": "tc_07a3299c", "keywords": ["calculu","exam","math","revision"],
     "text": "- Discord showing discord.com is part of this task (you confirmed 6 times).",
     "weight": 5.62, "evidence": 6, "last_evidence_at": 1757200000.0,
     "signature": "tc_07a3299c|discord.exe|domain:discord.com"}
  ],

  "allowances": [                      // mechanism (b)
    {"key": "tc_07a3299c|discord.exe|domain:discord.com",
     "cluster": "tc_07a3299c", "app": "discord.exe", "app_name": "Discord",
     "pattern": {"kind": "domain", "value": "discord.com"},
     "action": "pre_allow",            // or "downgrade"
     "title_patterns": [" - discord"], // lowercase substrings; required when pre_allow
     "evidence": 6, "distinct_days": 5, "rejected_presses": 4,
     "last_evidence_at": 1757200000.0, "expires_at": 1758400000.0,
     "why": "confirmed 6 times across 5 days"}
  ],

  "thresholds": [                      // mechanism (c)
    {"cluster": "tc_07a3299c", "app": "chrome.exe", "app_name": "Chrome",
     "block_threshold": 0.85, "false_alarms": 16, "missed": 0, "blocks_seen": 61}
  ],

  "decisions": {                       // pre-expanded lookup for Swift/Kotlin
    "math-test-prep|chrome.exe": {
      "prompt_suffix": "- Chrome showing wolframalpha.com is part of this task (you confirmed 4 times).",
      "pre_allow": true,
      "block_threshold": 0.85,
      "title_patterns": [" - wolfram alpha"]
    }
  },

  "integrity": { "score": 0.30, "notify_partner": false, "headline": "", "flags": [], "counters": {} },
  "stats": { "rows": 1248, "false_alarms": 127, "false_alarms_credited": 77, "...": 0 }
}
```

Three things about the schema are load-bearing:

**`defaults.block_threshold` is 0.0, meaning "no opinion".** The client's un-learned default is
also 0.0 (block every clean off-task verdict), so returning the learner's internal 0.55 anchor for
every unseen `(task, app)` would mean *switching learning on silently loosened the monitor across
the board, before it had learned anything*. A learning feature whose first act is to weaken the
tool is a bug, however well-motivated the number.

**`decisions` is a lossy projection of `apply()`, lossy in one direction only.** Swift and Kotlin
can't call Python, so the artefact carries a pre-expanded table keyed `"<task>|<app>"` using the
exact `lookupKey` normalisation in `macos/Guardian/Focus/LearnedPolicy.swift` (lowercase,
non-alphanumerics → spaces, that file's own stopword list, words of ≤2 chars dropped, first 4
joined with `-`). It has no title in the key, so it cannot express anything title-scoped. Both
consequences are resolved towards being *stricter* than `apply()`:

- a `downgrade` is title-scoped, so the map omits it entirely — a downgraded YouTube page still
  blocks on macOS where it wouldn't on Windows;
- `pre_allow` is emitted only for domain-kind allowances, never token-kind ones, because a client
  matches `title_patterns` with a substring test that ORs the two tokens of a token pattern where
  `apply()` requires both.

`test_decisions_map_is_never_looser_than_apply` asserts this over a whole simulated log: the map
never pre-allows a screen `apply()` would check, and never returns a higher threshold.

**No `*` wildcard rows are emitted.** The format supports them and the clients look for them, but
a wildcard carrying a real `pre_allow` would fire on tasks the learner has never seen — exactly
where `apply()` deliberately returns "no learning". A wildcard needs its own evidence rule ("this
app was excused under *every* task this user has ever declared"), not a default.

`title_patterns` are anchored to the **title tail** (`" - khan academy"`, not `"khan academy"`).
The naive version makes a client pre-allow `"Integration by parts | Khan Academy - YouTube"` —
a YouTube page that `apply()` correctly refuses to skip. A unit test covers it.

---

## What we measured

24 simulated days, 4 task families (math test prep, history essay, coding, job applications) with
3 freehand phrasings each, 1,248 judgements, 174 feedback presses. Chronological 60/40 split —
first 748 to learn from, last 500 to score on. Never a random split: the product claim is "it
stops repeating yesterday's mistake tomorrow", and a random split leaks tomorrow into yesterday.

"Before" is the action the simulated app actually took. "After" replays the same verdicts and the
same confidences through `policy.apply`. The model is held constant; the only variable is the
learner.

**Seed 20260908 (the default):**

|  | before | after | delta |
|---|---|---|---|
| false-alarm rate (of blocks) | 49.0% | **6.9%** | −42.2 pts |
| false alarms per 100 checks | 15.2 | **1.0** | −14.2 |
| **missed-violation rate** | **13.2%** | **25.3%** | **+12.1 pts — worse** |
| precision | 51.0% | 93.2% | +42.2 |
| recall | 86.8% | 74.7% | −12.1 — worse |
| F1 | 64.2% | 82.9% | +18.7 |
| blocks | 155 | 73 | −82 |
| model calls | 500 | 380 | −120 |

**82 blocks prevented: 71 were false alarms, 11 were genuine distractions that got through.** A
6.5 : 1 trade. Whether that trade is worth taking is a product decision, not a modelling one, and
the number is here so it can be made honestly. 120 model calls saved (24%) is a real cost saving
on a 2-minute cadence, and it's the one benefit that doesn't depend on the model being wrong.

**Ablations** (same test set):

| | FA rate | missed | precision | recall |
|---|---|---|---|---|
| before (no learning) | 49.0% | 13.2% | 51.0% | 86.8% |
| allowances only (b) | 19.4% | **13.2%** | 80.6% | **86.8%** |
| calibration only (c) | 20.0% | 25.3% | 80.0% | 74.7% |
| all mechanisms | 6.9% | 25.3% | 93.2% | 74.7% |

**Allowances (b) are the mechanism that earns its place.** They cut the false-alarm rate from 49%
to 19% *at zero cost to recall* — because they are scoped to an exact `(task, app, title-pattern)`
triple, so nothing else in the app is loosened. Calibration (c) achieves a similar false-alarm
reduction but pays for all of the recall loss: **every point of the +12.1 missed-violation rise
comes from (c), none from (b).** They are complementary rather than redundant — together they
reach 6.9%, better than either alone — but if you had to ship one, ship (b).

**Across five seeds** (same generator, different random draws):

| seed | FA before | FA after | missed before | missed after | F1 after |
|---|---|---|---|---|---|
| 11 | 48.1% | 5.3% | 6.0% | 28.0% | 81.8% |
| 20260908 | 49.0% | 6.9% | 13.2% | 25.3% | 82.9% |
| 4242 | 49.3% | 8.3% | 18.9% | 30.5% | 79.0% |
| 777 | 47.3% | 7.1% | 13.7% | **49.0%** | 65.8% |
| 90210 | 40.5% | **14.6%** | 16.1% | 32.1% | 75.6% |

The false-alarm reduction is robust (5.3–14.6% after, from ~40–49% before). **The recall cost is
not.** Seed 777 loses nearly half of all genuine distractions, driven by a calibration threshold
that hit the 0.85 ceiling on a browser the user does everything in. That is the honest headline
risk of mechanism (c) and the strongest argument for shipping (b) first and (c) behind a flag.

**Mechanism (a), exemplar memory: NOT MEASURED.** It works by changing what the model *answers*,
and replaying a log cannot re-ask the model. Inventing an "assumed 30% improvement from few-shot"
would make this whole section fiction. What we can report is **coverage**: 73 of 76 test-set false
alarms (96.0%) would have reached the model with a relevant exemplar already in the prompt (mean
suffix 219 characters of the 1200 budget, so the budget is not the binding constraint). That is
an upper bound on its reach, not an effect. Measuring it needs an online A/B against a live model.

### The anti-gaming guard, measured

A second simulated user who additionally presses "False alarm" on genuine distractions,
reflexively, 85% of the time:

| policy trained on | FA rate | missed | recall |
|---|---|---|---|
| honest feedback | 6.9% | 25.3% | 74.7% |
| spammed feedback | 20.8% | 33.0% | 67.0% |

**198 false-alarm presses, 51 credited, 147 (74%) refused by the guard.** The spammer ends up
with 6 allowances instead of the honest user's 9, and integrity 1.00 with the partner alert fired
against the honest user's 0.30 and silence. Note honestly what this does *not* say: spamming
still costs 7.7 points of recall. The guard **bounds** the damage and makes it **visible**; it
does not eliminate it. Guard 9 — the partner notification — is doing more work here than guards
1–8 combined, which is why it exists.

### A finding worth keeping

For the maths task, `chrome.exe + youtube.com` accumulated **6 confirmed false alarms and 5
`correct` presses** — because the Khan Academy lecture and the Minecraft speedrun are the *same
signature* at domain granularity. Net evidence 1, so no allowance and no exemplar was created.
The mechanism refused to learn something it could not learn safely, which is the designed
behaviour (guard 5) and also the clearest statement of the granularity limit below.

---

## Limitations / what would break this

**1. Domain granularity cannot separate a lecture from a let's-play.** The biggest one. YouTube
serves both, and a `(cluster, app, domain)` signature sees one thing. The measured consequence is
above: for maths, YouTube can never earn an allowance, so the single most common false alarm in
the whole product is the one case (b) cannot fix. Fixing it needs a signal we don't extract —
channel name, video title keywords, or the model's own reason string — and every one of those is
a new surface for the user to game. Until then, YouTube false alarms depend entirely on mechanism
(a), which is unmeasured.

**2. Calibration is app-wide, and it is the recall killer.** A raised threshold for
`(math, chrome.exe)` applies to every Chrome window, TikTok included. The ablation shows all of
the +12.1-point missed-violation rise comes from here, and seed 777 shows it can reach 49%. It is
also, against the client's current default of 0.0, **only able to loosen** — a `missed`-driven
threshold of 0.40 is still above 0.0, so the tightening half of the mechanism is inert until the
app adopts a non-zero default. Ship (b) first; put (c) behind a flag.

**3. Everything above is measured on synthetic data, and the simulator is the hypothesis.** The
`p_flag` values are guesses about a model nobody has profiled. If the real model's errors are
less systematic than assumed, (a) and (b) both degrade towards nothing — a false alarm with no
recurring signature cannot be learned from. The next experiment is not more tuning, it is 200
labelled screenshots from real sessions and a live A/B for (a). Nothing in this README should be
quoted as a claim about the shipping product.

Smaller ones, in descending order of how likely they are to bite:

- **Feedback is rare and biased.** 174 presses over 1,248 checks, and only on screens that were
  *blocked* — false negatives are invisible unless the user volunteers `missed`. The learner is
  trained almost entirely on one tail of the distribution.
- **Task clustering is a set-containment score over stemmed tokens**, not semantics. "prepping for
  Thursday" and "math test prep" share nothing and become two clusters, each learning separately.
  Containment at 0.33 with single linkage is also chain-prone in principle; it is kept safe only
  because generic verbs ("work", "doing", "session") are stopwords, and that list is hand-written.
- **The `SITE_NAMES` table is hand-maintained** and biased towards English-language Western sites.
  An unrecognised site falls back to token patterns, which are weaker and never earn a
  `pre_allow` on macOS or Android.
- **A determined user still wins eventually.** Six credits per signature, twelve per day, two
  days minimum — a patient adversary reaches every allowance the honest user does. The guard buys
  time and generates evidence; the accountability partner is the actual control.
- **Window titles leak.** They are the input to every signature, so the policy file contains
  domains and title fragments. Cluster *ids* are hashed so the file's keys don't carry task text,
  but `label`, `exemplars[].text` and `title_patterns` do. Treat `focus_policy.json` as private
  data; it is not safe to attach to a bug report.
- **Local-time day bucketing.** Guard 4 counts calendar days in local time, so a user who travels
  across enough timezones can manufacture an extra "distinct day". Low impact, real.
