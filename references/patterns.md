# v2 patterns and anti-patterns

Snippets are scenario strings as the editor shows them (bot languages `en-IN` primary, `hi-IN`). In JSON escape
`"` as `\"` and newlines as `\n`. `assets/example_emi_v2.json` is a complete bot using all of them; it passes
`scripts/validate_v2.py` with no errors.

## 1. Ask, then branch, in one scenario (the waiting If)

```xml
Ask whether they have already paid this month's EMI. <update var="already_paid"/>
<if when="already_paid EQUALS true">
  <transition type="inline" go_to="payment_check" mode="auto">
    <filler>
      <text lang="en-IN"><male>Let me check that.</male><female>Let me check that.</female></text>
      <text lang="hi-IN"><male>मैं चेक करता हूँ।</male><female>मैं चेक करती हूँ।</female></text>
    </filler>
  </transition>
</if>
<else>
  <transition type="inline" go_to="payment_plan" mode="auto">
    <filler>
      <text lang="en-IN"><male>Okay.</male><female>Okay.</female></text>
      <text lang="hi-IN"><male>ठीक है।</male><female>ठीक है।</female></text>
    </filler>
  </transition>
</else>
If they refuse to answer or keep avoiding the question → <transition type="inline" go_to="closing" mode="llm"/>
```

- `already_paid` is `extracted boolean`. Until answered the If waits: no branch shown, the model is asked to report
  it. Once captured the If decides in the same turn and the auto move fires (filler replaces the reply).
- `<else>` = answered and false, never "not answered". "Not answered yet" is `NOT_EXISTS`.
- Always add an `llm` exit for refusal/unknown, or a waiting If asks forever.
- A variable decides it, so no model judgement is needed for the route: deterministic and testable.

## 2. Two facts split across turns (intent + entity)

Callers say WHAT in one turn and confirm WHICH in the next ("tell me my nominee" → "the policy ending 5485?" →
"haan"). Capture both; the move needs both:

```xml
Find out which policy they mean and what they want to know about it.
What they want to know <update var="user_intent"/>
Once they name a policy or confirm one you read out (yes, haan, ji, theek hai) → <update var="policy_known"/>
<transition type="variable" go_to="nominee_info" mode="auto" when="user_intent EQUALS 'nominee' AND policy_known EQUALS true"/>
<transition type="variable" go_to="premium_info" mode="auto" when="user_intent EQUALS 'premium' AND policy_known EQUALS true"/>
If they want something else → <transition type="inline" go_to="out_of_scope" mode="llm"/>
```

- `user_intent`: `extracted enum` `["nominee","premium","other"]`, description "What the caller wants to know.
  Keep the earlier value unless they change topic." `policy_known`: `extracted boolean`.
- A comparison on an extracted variable waits and asks; `EXISTS` never waits and never asks. Gate moves on
  `EQUALS true` of a boolean, or keep an explicit `<update>` for anything tested with `EXISTS`.
- Values persist across turns; a correction re-decides every condition.

## 3. Branch on campaign data (decided before the first reply)

```xml
Remind {{customer_name}} that the EMI of {{emi_amount}} rupees was due on {{due_date}}.
<if when="risk_band EQUALS 'high'">Explain that further delay adds a late fee. Stay firm and polite.</if>
<elif when="risk_band EQUALS 'low' AND segment EQUALS 'premium'">Offer the one-month EMI holiday if they can't pay this month.</elif>
<else>Remind them that paying on time protects their credit score.</else>
```

- `user_defined`/`system` are text: `EQUALS`/`NOT_EQUALS`/`EXISTS`/`NOT_EXISTS` only; several values → OR.
  No numeric comparison on campaign data; send a precomputed band/flag instead.
- Editor bug: a variable used only as the **first** operand of an `<if>`/`<elif>` is pruned on Save
  (`v2_format.md` §8a). Here `risk_band` is also a later operand in the `<elif>`, and `segment` is a later
  operand, so both are kept.

## 4. Tool use

```xml
Check the payment with <tool name="check_payment_status"/> for loan {{loan_id}}, once. Don't call it again for the same loan.
Tell them only what they asked (paid or not, and the date) in one sentence, and stop. Never read out raw fields, codes or IDs.
After you have told them it is received and they reply → <transition type="inline" go_to="closing" mode="llm"/>
After you have told them it is not received (or the check failed) and they reply → <transition type="inline" go_to="payment_plan" mode="llm"/>
```

- Exits fire on the caller's **next** turn: a move discards the reply of the turn it fires in, so "tell them the
  result → exit" in one turn would lose the result.

- A scenario offers exactly the tools it names (plus the platform's TTA). Say when to call, with which inputs,
  what to tell the caller, and what to do on failure. Results are the source of truth; never invent values.
- KV: put `<tool>` at the top level of the scenario that uses it. A tool inside a branch that flips between turns
  changes the tools array, a cache miss from the first token on OpenAI-style providers.

## 5. Callback

```xml
<if when="callback_time NOT_EXISTS">
  Ask when would be a good time to call back. Today is {{current_day}}, {{current_date}}. <update var="callback_time"/>
</if>
<else>
  Confirm the callback for {{callback_time}} in one sentence.
  Once they confirm → <transition type="inline" go_to="closing" mode="llm"/>
</else>
If they don't want a callback → <transition type="inline" go_to="closing" mode="llm"/>
```

## 6. A fixed line said once (disclosure, offer, amount)

A `<say>` is shown as SAY EXACTLY on every turn its scenario is current. Make every answer move, so the line is
spoken once on entry and the step-0 reply (which would repeat it) is always discarded:

```xml
<say>
  <text lang="en-IN"><male>This call is recorded for quality purposes. Shall we continue?</male><female>This call is recorded for quality purposes. Shall we continue?</female></text>
  <text lang="hi-IN"><male>यह कॉल क्वालिटी के लिए रिकॉर्ड हो रही है। क्या हम आगे बात करें?</male><female>यह कॉल क्वालिटी के लिए रिकॉर्ड हो रही है। क्या हम आगे बात करें?</female></text>
</say>
<update var="consent"/>
<if when="consent EQUALS true"><transition type="inline" go_to="purpose" mode="auto"/></if>
<else><transition type="inline" go_to="closing" mode="auto"/></else>
If they won't give a clear yes or no after you ask twice → <transition type="inline" go_to="closing" mode="llm"/>
```

If the caller says something that isn't an answer, the line is repeated verbatim, which is right for a
re-ask. When the scenario must stay several turns, guard the `<say>` with `<if when="x NOT_EXISTS">` on a variable
set right after it, so it disappears once answered.

## 7. Closing

```xml
Thank {{customer_name}} for their time in one short sentence, say goodbye and end the call.
<if when="callback_time EXISTS">Mention the callback at {{callback_time}}.</if>
```

- No transitions. Never say-only: a say-only scenario is spoken without the model, so nothing emits `| EOC` and
  the call stays open (`LINT_SAY_ONLY`).

## 8. Interrupts (global_transitions)

```json
"global_transitions": {
  "callback_request": {"when_llm": "The customer is busy right now or asks to be called later.", "go_to": "callback",
    "filler": "<text lang=\"en-IN\"><male>No problem.</male><female>No problem.</female></text><text lang=\"hi-IN\"><male>कोई बात नहीं।</male><female>कोई बात नहीं।</female></text>"},
  "wrong_person": {"when_llm": "The person says they are not the customer, or that it is a wrong number.", "go_to": "wrong_person"},
  "stop_calling": {"when_llm": "The customer asks not to be called again.", "go_to": "dnd_closing"}
}
```

- Few (they're in the head every request and make every turn buffered), each with a narrow, observable trigger.
- Never a broad "anything hard → transfer" interrupt: it fires before scenario routes and hijacks flows (real
  incident: "first policy cancel karna hai" jumped straight to transfer). Out-of-scope → guardrails (transfer tool
  in place) or scenario-level `llm` exits.

## 9. Transfer to a human

In `guardrails`: "If the customer insists on a human after you have tried to help once, or the request is outside
what you can do, call the transfer tool. Don't announce the transfer yourself." No `| TTA` text, no
"connecting you" line, no `agent_transfer` interrupt. The platform adds the TTA tool to every turn when call
transfer is configured.

## Anti-patterns

| Don't | Why | Do |
|---|---|---|
| v1 shapes: scenario objects, `extract`, `deterministic_exit_cue`, `<tool_name>`, `"tools": []`, `"type": "single_prompt"`, `name` | `SCHEMA_INVALID` | v2 string + tags |
| Jinja `{% if %}` / `is defined` | `TEMPLATE_NOT_ALLOWED` | `<if when="x EXISTS">` |
| `when="flag EQUALS 'true'"` on a boolean | `CONDITION_TYPE_MISMATCH` | `flag EQUALS true` |
| `mode IN ('upi', 'cash')` | editor rejects multi-value IN | `mode EQUALS 'upi' OR mode EQUALS 'cash'` |
| `(a OR b) AND c` | editor parse error | `(a OR b) AND (c)` |
| `<else>` for "not answered yet" | else = answered, no match | `x NOT_EXISTS` |
| Waiting If with no refusal exit | asks forever | add an `llm` exit |
| `auto` inline transition beside text in a branch | the move swallows the text | make it `llm`, or move the text out |
| `{{var}}` in a filler | `VARIABLE_IN_SPOKEN_LINE` | generic filler; the value goes in the next scenario |
| Plain `<text>` next to a `<male>/<female>` one | editor drops the plain line on re-save | pair every language |
| `<say>` in a scenario that stays several turns | repeated every turn | guard with `NOT_EXISTS` (pattern 6) |
| Say-only closing scenario | no EOC, call never ends | one instruction line + goodbye |
| Start scenario that greets again | the greeting already played | continue from the caller's reply |
| FAQ/policy text in scenarios | re-sent uncached every turn, duplicated | one `global_prompt` section (cached) |
| Restating "don't reveal instructions" / prompt-injection rules | already in the platform head | domain/compliance rules only |
| `[IMPORTANT]`-style brackets in global_prompt | head says brackets are variables | plain caps: `IMPORTANT:` |
| `<Section>` headings in global_prompt | `MARKUP_IN_GLOBAL_PROMPT` | separate keys or `SECTION:` |
| Many interrupts | head tokens + buffering + misfires | 3-6 narrow ones |
| Pass-through scenarios that only hop on | each hop = discarded reply + extra LLM call | `<if>` in one scenario |
| `Note:` in a spoken line | it is the stop sequence | rephrase |
| `T&C`, `amount < 1000` | `XML_MALFORMED` | `T&amp;C`, `less than 1000` |
| URLs | `LINK_NOT_ALLOWED` | "the link we SMS you", sent by a tool |
