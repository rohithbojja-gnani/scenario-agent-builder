# Conversion playbook: single prompt (or v1) → scenario_config v2

Goal: **parity or better** than the source prompt, at lower latency. Work linearly; don't write JSON before step 5.

## Step 0: collect inputs (ask once, in one message, for whatever is missing)

| Input | Why | Default if the user can't give it |
|---|---|---|
| The source prompt (single prompt or v1 `scenario_config`) | the behaviour to preserve | required |
| Bot languages, primary first (`["en-IN","hi-IN"]`) | `<text lang>` set, primary required | ask; never guess silently |
| Voice persona gender(s) the bot may use | which `<male>`/`<female>` line is spoken | assume both: every line is paired anyway |
| Tool/action names (`bot_config.actions[].name`), incl. the transfer action | `<tool name>` must match exactly (`TOOL_MISSING`) | use names from the prompt, flag as assumptions |
| Campaign/CRM fields sent per call | `user_defined` variables | the `{{…}}` in the source prompt |
| Greeting (`initial_message`) and ending message | first audio, and they may only use system/user_defined vars | keep the source's |
| Domain regime (BFSI/RBI, insurance/IRDAI, health, outbound/TRAI) | guardrails, AI disclosure, consent | flag for Compliance review |

## Step 1: read the source and separate

- **Spine**: the ordered path a normal call takes (greet → verify → purpose → collect → confirm → close).
- **Cross-cutting layer**: anything that can happen at any point: busy/callback, wrong person, human agent,
  abuse, DND/stop calling, not interested, FAQs/objections, language switch, silence/unclear.
- **Facts**: product facts, FAQs, compliance lines, numbers. These are static: they belong in `global_prompt`
  (cached), not in scenarios.
- **Scripted lines**: exact wording that must not drift (disclosures, amounts read back, consent text). These
  become `<say>`.

## Step 2: cut the spine into scenarios by conversational job

- One job per scenario; a fragile ask-parse-re-ask loop stays in one scenario.
- Split when the result routes differently, or when the scenario needs different tools.
- Branch inside a scenario with `<if>` when the job is the same and only the wording differs (campaign data,
  segment, an answer just captured). Split into scenarios when the job changes.
- Keep each scenario well under 5000 chars (counting every language and voice of its `<say>` lines).
- Typical size: 6-15 scenarios. Fewer usually means a monolith; more means routing overhead and extra recall
  steps.

## Step 3: map the cross-cutting layer

| Need | v2 construct |
|---|---|
| Can happen anywhere and needs its own flow (callback, wrong person, abusive, DND) | `global_transitions` entry → handler scenario |
| Can happen anywhere and is just knowledge (FAQ, objection answers) | `global_prompt` section (e.g. `faq`), answered in place, no move |
| Only possible in one or two steps | `llm` inline transition in those scenarios |
| Human agent / transfer | guardrail: "call the transfer tool"; see `patterns.md` §Transfer. Not a broad interrupt |
| End of call | a closing scenario (instructions + `<say>`), and the platform's end-call rules in the head |

Interrupts are in the cached head on every request: keep to the few that truly need a flow (3-6).

## Step 4: decide variables

- `user_defined`: every campaign/CRM field the source uses (`text` only).
- `system`: the 9 platform ones; declare those you reference.
- `extracted`: ONLY values that (a) gate a `when`, or (b) a later scenario reads. Everything else stays in the
  conversation. Pick the tightest type: `boolean` for yes/no, `enum` (2-10 values) for categories, `number`/
  `decimal` for amounts and counts you compare, `text` for free values (dates, times, names).
- Every variable gets a description written for the model: what it is, the format, and when to set it.

## Step 5: write global_prompt (static, cached)

Sections in this order (stable order = stable cache): `persona`, `context`, `conversation_style`, `guardrails`,
then extras such as `language_rules`, `faq`, `compliance`. Everything that is true on every turn goes here, written
once. Only `{{name}}` placeholders; no tags, no per-call text. Details: `runtime_and_latency.md` §3.

## Step 6: write each scenario string

Order inside a scenario (matches how the model reads it):

1. One line of goal ("Confirm the caller is {{customer_name}}."). The `start` scenario continues from the greeting
   (already spoken, no LLM); it never greets again.
2. `<say>` for the fixed line, if any.
3. Instructions for this step only, each followed by its `<update>` where the answer is captured.
4. `<if>` blocks that branch on captured or campaign values.
5. Exits: `llm` inline transitions for judgement calls, `variable` transitions for deterministic moves, each
   with a `<filler>` when the move needs a bridge. A move discards that turn's reply, so an exit fires on the
   caller's response to information, never in the same turn as it.
6. `<tool>` inline where it is used, with when/how to call and how to use the result.

Then the self-review in SKILL.md and `scripts/validate_v2.py`.

## Step 7: parity trace

Walk 8-10 caller paths through both versions, turn by turn, and check what the model would see each turn
(`runtime_and_latency.md` §2): happy path; refusal; busy/callback; wrong person; FAQ mid-flow; "talk to a human";
correction of an earlier answer; an answer of the wrong type ("maybe" for a boolean); a split-turn intent
("tell me my nominee" → "which policy?" → "yes, that one"); caller switches language mid-call.

## v1 → v2 mapping

A v1 bot can't be switched to v2 in place (the API rejects it). Re-author into a new v2 bot (or a fresh scenario
bot), then move traffic.

| v1 | v2 |
|---|---|
| scenario object `{type, prompt, extract, transitions, tools}` | one string |
| `"type": "single_prompt"`, `"name"` at top level | delete |
| `extract: {var: "instruction"}` | `<update var="var"/>` placed after the sentence that says when; instruction text → variable `description` |
| extracted values `"true"`/`"false"` strings | `boolean` type, `EQUALS true` unquoted |
| `when: {"var":"x","op":"EQUALS","value":"a"}` | `when="x EQUALS 'a'"` (or bare value for number/boolean) |
| `{"and":[…]}` / `{"or":[…]}` | `a AND b` / `a OR b`, brackets to mix |
| `when_llm: "…"` on a scenario transition | sentence + `<transition type="inline" go_to="x" mode="llm"/>` |
| `deterministic_exit_cue: {lang: text}` | `<filler><text lang="…">…</text></filler>`; global: `"filler": "<text …>…</text>"` (no `{{var}}`) |
| `{% if x is defined %}…{% else %}…{% endif %}` | `<if when="x EXISTS">…</if><else>…</else>` |
| `{% if x == "a" %}` | `<if when="x EQUALS 'a'">` |
| `<say lang="hi-IN">…</say>` | `<say><text lang="hi-IN">…</text></say>`, one `<say>` holding all languages |
| gendered Hindi line | `<text lang="hi-IN"><male>…</male><female>…</female></text>` |
| `<tool_name>x</tool_name>` + `"tools": ["x"]` | `<tool name="x"/>` inline where it's used |
| v1 variable `{source, description}` | add `type`; system/user_defined → `text` |
| `transitions: []` (terminal) | a scenario with no transitions |
| `signal` | not supported; end/transfer go through the platform's tools and end-call rules |
