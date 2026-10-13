# Conversion playbook: single prompt → version 2, and version 1 → version 2

The goal is **parity or better**: the version 2 agent must answer at least as well as the source, and must pass
the save-time validator. Keep every customer-facing scripted line word for word unless it has an obvious error
(say which ones you fixed).

## A. Single prompt → version 2

### A1. Read the whole prompt and separate

- **The spine**: the ordered path a normal call takes (collections: greet → identity → status → offer → date →
  amount → mode → read-back → close; lead: greet → interest → eligibility → offer → link → close).
- **The cross-cutting layer**: things that can happen anywhere (busy/call later, talk to a human, abuse, DND,
  wrong number, distress or death, already paid, not my loan, FAQs).
- **Shared rules**: rules that apply in many steps (date resolution, how to speak amounts, FAQ answers, compliance
  lines).

### A2. Cut the spine into scenarios by conversational job

- One job per scenario ("confirm identity", "present the offer", "capture the date").
- Keep a fragile sub-routine whole (ask, parse, re-ask of one fact).
- Split where the outcome routes differently, and where a scenario would exceed **5000 characters**.
- A large agent typically has 8 to 18 scenarios. Fewer means the monolith survived; many more means steps that
  don't route differently were split.

### A3. Map the cross-cutting layer

| Situation | Version 2 shape |
|---|---|
| Busy / call later | Global interrupt → `callback` scenario (window check, read-back, close) |
| Abuse, DND, recording, unsupported language | Global interrupt → a closing scenario, or deterministic flags in the scenarios where they are likely |
| Death / distress | Global interrupt → a terminal scenario with no collection |
| Wrong number, third party | Branches in the identity scenario → dedicated scenarios |
| Already paid, not my loan | Variable transitions in every scenario where they can happen (report the flag + disposition together) |
| FAQs answered anywhere | An extra global prompt section with the approved answers; "answer, then resume the current ask" |
| Talk to a human | The transfer tool from the scenario (no broad interrupt); a dedicated scenario only if a script must run first |

Each global interrupt needs its own target scenario.

### A4. Global prompt

- `persona`, `context`, `conversation_style`, `guardrails` from the prompt's identity, purpose, style and
  compliance parts.
- **Extra sections for shared rules** (e.g. `shared_rules`, `date_rules`, `faq_reference`). They are shown on every
  turn and cached, so moving shared rules here also shrinks the scenarios. Each section ≤ 3000 characters.
- Plain text plus `{{name}}`; no tags, no Jinja.

### A5. Variables (see `references/variables.md`)

- `system` (the nine platform variables) and `user_defined` (campaign data) are `text`.
- `extracted` only for values that route the call, cross a scenario boundary, or are required outputs
  (dispositions, committed date/amount). Give each a type: `boolean` flags, `enum` for 2 to 10 categories, `text`
  for dates, names and codes with more than 10 values, `number`/`decimal` for amounts compared in conditions.

### A6. Write each scenario

Typical layout (instructions, then what to report, then the moves):

```xml
STATE: offer_said={{tier1_offer_delivered}}, reason={{payment_reason}}
<goal of the scenario in one or two sentences>

WHEN THIS SCENARIO STARTS: <the opening line, verbatim>

<how to handle each kind of answer, in short labelled lines>
If they ask to be called later → <transition type="inline" go_to="callback" mode="llm"/>

REPORT when it applies:
<update var="settlement_offer_accepted"/>
<update var="route_choice"/>

<transition type="variable" go_to="payment_date_capture" mode="auto" when="settlement_offer_accepted EQUALS true"><filler><text lang="hi-IN">ठीक है।</text><text lang="en-IN">Okay.</text></filler></transition>
<transition type="variable" go_to="rejection_reason" mode="auto" when="settlement_tier1_refused EQUALS true"/>
```

Rules of thumb:
- The opening line of a scenario belongs to that scenario (it is spoken right after the move into it).
- Every moving decision is a flag the model reports, plus a variable transition on it, ordered most specific
  first. Outcome flags (dispositions) are reported in the same turn.
- Conditional wording on known values → `<if>`. "Ask X then branch on X" → a waiting `<if>` on X.
- Tools: `<tool name="…"/>` next to the instruction that uses it, inside the branch where it applies.
- Spoken fixed lines → `<say>` only if they contain no `{{name}}`; otherwise give them as quoted instructions
  ("say verbatim: …").

### A7. Budget the size

Measure every scenario string (tags included). Over ~4800 characters: move shared rules to a global prompt
section, cut repeated WRONG/RIGHT lists, express variants as prefix + shared core, or split the scenario at a
natural boundary (ask-the-reason vs make-the-offer, date vs amount/mode).

### A8. Validate and self-test

Run `scripts/check_v2.py` (or the checklist in SKILL.md). Then trace 8 to 10 customer inputs through both versions:
happy path, refusal with reason, busy, an FAQ mid-flow, a correction, wrong number/third party, already paid,
not my loan, silence, and a split-turn intent (intent in turn 1, a bare "haan" in turn 2).

## B. Version 1 → version 2

### B1. Field mapping

| Version 1 | Version 2 |
|---|---|
| `scenarios.x = {type, prompt, extract, transitions, tools}` | `scenarios.x = "<one string>"` |
| `prompt` text | Scenario text (escape or reword `&` and `<`) |
| `{% if a is defined %}…{% else %}…{% endif %}` | `<if when="a EXISTS">…</if><else>…</else>`, or keep the wording plus a STATE line |
| `{% if a == "x" %}` | `<if when="a EQUALS 'x'">` (typed value) |
| `<say lang="L">line</say>` pairs | `<say><text lang="L1">…</text><text lang="L2">…</text></say>` (no `{{name}}` inside; otherwise a quoted instruction) |
| `<tool_name>t</tool_name>` + `tools: ["t"]` | `<tool name="t"/>` where the tool is used |
| `extract: {v: "instruction"}` | Instruction sentence + `<update var="v"/>`; drop "preserve" entries (values persist) |
| `{"var": v, "op": "EQUALS", "value": "true"}` | `v EQUALS true` |
| `{"and": [...]}` / `{"or": [...]}` | `… AND …` / `… OR …` (one joiner); mixed groups → nested Ifs or two transitions |
| `NOT_EQUALS "true"` on a boolean flag | Not allowed: put the transitions that test those flags first, or use `NOT_EXISTS` |
| `when_llm` transition | `<condition sentence> → <transition type="inline" go_to="x" mode="llm"/>` |
| `deterministic_exit_cue` | `<filler>` (primary language first, all languages) |
| Terminal scenario `transitions: []` | No transitions; closing line ends with `\| EOC` |
| Global transition `{when_llm, go_to, deterministic_exit_cue}` | `{when_llm, go_to, filler}` with `<text>` lines; no `type` |
| `conversationStyle` | `conversation_style` (both accepted) |
| `system` campaign fields | `user_defined`, `text` |
| String "true"/"false" extracted values | `boolean` |
| Enumerated strings ("a \| b \| c") | `enum` with `allowed_values` (2 to 10; otherwise `text` and list the values in the description or a global section) |

### B2. Re-check version 1 workarounds — they often break in version 2

Version 1 prompts often carry instructions written around the version 1 engine. Rewrite them:

| Version 1 instruction | Version 2 |
|---|---|
| "Deliver the next scenario's OPENING on this turn" | Remove; the next scenario speaks its own opening right after the move |
| "Emit NO spoken text — the system routes to X" | Remove; the move discards the reply. Silence is risky if the move doesn't happen |
| "Same-turn silent handoff" in the destination | "WHEN THIS SCENARIO STARTS: say <opening>" |
| "Set X_delivered true when you say line L" (line said on entry) | Report it on the customer's next turn ("including when it was said as this scenario started"); don't gate moves on it |
| "terminal_disposition = … in extract" inside a closing scenario | Report it in the scenario that decides to close, with the triggering flag |
| "if flag is true …" in plain text | STATE line with `{{flag}}`, or `<if>` |
| `[current_day]` style references | `{{current_day}}` |
| A huge scenario (8–15k characters) | Shared rules to global sections, then condense or split (≤ 5000) |

### B3. Then follow A4–A8.

## C. From a description

Ask for (or assume and state): languages and primary language, the bot's tool/action names, campaign variables,
the dispositions or outcomes to record, compliance lines. Then A2–A8.

## D. Compliance checks while converting (flag, don't silently change)

- The opening must disclose that the caller is an AI assistant.
- Collections: no threats or intimidation; legal-consequence lines and asking a borrower to borrow from friends or
  family need compliance review; calling windows (typically 09:00–19:00 local); respect DND requests.
- Never speak account numbers or personal data to a third party or to someone who denies the loan.
- Healthcare, insurance and lending scripts: keep approved FAQ wording; mark any missing approved text
  `[TO CONFIRM]` instead of inventing it.
