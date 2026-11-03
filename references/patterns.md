# Patterns and anti-patterns (version 2)

All examples use placeholders ([BANK_A], [CUSTOMER]). Languages: `hi-IN` primary, `en-IN` second.

## Identity with a waiting If (ask, then branch, in one scenario)

```xml
Greet the customer and introduce yourself as {{agent_name}}, an AI assistant from [BANK_A].
Ask if you are speaking with {{customer_name}}. <update var="identity_confirmed"/>
<if when="identity_confirmed EQUALS true">
  <transition type="inline" go_to="emi_reminder" mode="auto">
    <filler><text lang="hi-IN">पुष्टि करने के लिए धन्यवाद।</text><text lang="en-IN">Thank you for confirming.</text></filler>
  </transition>
</if>
<else>
  <transition type="inline" go_to="wrong_person" mode="auto"/>
</else>
If they are busy and ask to be called later → <transition type="inline" go_to="callback" mode="llm"/>
```

Turn 1: the If waits, the model asks. Turn 2: "haan" → captured → the If is decided → the call moves in that turn.
`<else>` only runs once the answer is captured and is not true.

## Split-turn intent (intent in one turn, entity confirmed in the next)

Capture both as variables and move only when both are known; `when_llm` fails on a bare "haan" turn.

```xml
Find out which policy the caller means and what they want to know.
Policy: by last four digits, product name, or a confirmation (yes, haan, ji haan, theek hai) when you name one.
<update var="selected_policy"/>
Topic: policy, premium, nominee, fund or claim. Take it from the whole conversation; once set, keep it unless they change topic.
<update var="user_intent"/>
<transition type="variable" go_to="nominee_info" mode="auto" when="selected_policy EXISTS AND user_intent EQUALS 'nominee'"/>
<transition type="variable" go_to="premium_info" mode="auto" when="selected_policy EXISTS AND user_intent EQUALS 'premium'"/>
```

## STATE line (let the model see the values it must reason about)

```xml
STATE: offer_said={{tier1_offer_delivered}}, reason={{payment_reason}}, wont_pay={{wont_pay_stated}}
```

Rendered with values (empty = not set). Use it when converting a large version 1 prompt whose plain-text gates
read variables; prefer `<if>` for new designs.

## Opening line of a scenario (spoken right after the move into it)

```xml
WHEN THIS SCENARIO STARTS: say the OFFER verbatim, then wait:
Hindi: "हम आपको एक one-time settlement offer दे रहे हैं — … क्या आप इस offer को accept करते हैं?"
English: "We are offering a one-time settlement of … Do you accept this offer?"
Never replay the full OFFER once said; for unclear audio only, ask: "Do you accept this one-time settlement offer?"
```

## Variants as prefix + shared core (saves characters)

```
WHEN THIS SCENARIO STARTS: say exactly one line. CORE is: "<offer line>"
- wont_pay true → CORE alone.
- hardship → "<empathy prefix> — " immediately followed by CORE.
- otherwise → "<firm acknowledgement> — " immediately followed by CORE.
```

## Outcome reported on the deciding turn

```xml
On that confirm only: ptp_confirmed true, ptp_window, and terminal_disposition AGREED_SETTLEMENT_LESS_THAN_7_DAYS
(…the matching code). The closing scenario speaks the close on this same turn; say no closing line here.
<update var="ptp_confirmed"/> <update var="ptp_window"/> <update var="terminal_disposition"/>
<transition type="variable" go_to="ptp_closing" mode="auto" when="ptp_confirmed EQUALS true"><filler>…</filler></transition>
```

The closing scenario then has no `<update>`: its single reply ends the call.

## Closing scenario chosen by an outcome code

```xml
STATE: terminal_disposition={{terminal_disposition}}
Say ONLY the line matching terminal_disposition, verbatim. If it is empty: DND if they asked not to be called again,
otherwise GENERAL.
WRONG_NUMBER: "माफ़ कीजिए, गलत नंबर लग गया। धन्यवाद। | EOC"
DND: "समझ गई, आपको दोबारा call नहीं करेंगे। धन्यवाद। | EOC"
GENERAL: "धन्यवाद। | EOC"
```

## Shared rules in a global prompt section

```json
"shared_rules": "ALREADY PAID (any turn): customer says already pay, payment ho gaya, kar diya → route_choice already_paid and terminal_disposition ALREADY_PAID. WRONG: receipt, reference, re-collection.\nLOAN DENIED (any turn): ... → loan_denied true and terminal_disposition NOT_AWARE_ABOUT_LOAN."
```

Each scenario that can move on these flags names them (`<update>` or a transition) and says "see SHARED RULES".

## Tool scenario

```xml
Answer the caller's question about their chart from the tool result only.
If you don't have a result for this question in this call, call <tool name="get_chart_evidence"/> first, without
announcing it. Give only what was asked; never read raw fields or IDs. If it fails, call the transfer tool without
a spoken line. Put any report after your final answer.
```

## Callback with a calling window

```xml
Ask when to call back. Resolve: date only → 10:00; morning 10:00, afternoon 14:00, evening 17:00.
Valid times are 09:00 to 18:59 local; outside it, say once: "Sorry, we can only call between 9 AM and 7 PM — what time works?"
Read back once, only an in-window time. Confirmed → callback_confirmed true, terminal_disposition ASKED_FOR_CALL_BACK.
<update var="scheduled_callback_time"/> <update var="callback_confirmed"/> <update var="terminal_disposition"/>
```

## Global interrupts

```json
"global_transitions": {
  "reschedule": {"when_llm": "The customer is busy, driving, in a meeting, or asks to be called later.", "go_to": "callback",
                 "filler": "<text lang=\"hi-IN\">कोई बात नहीं।</text><text lang=\"en-IN\">No problem.</text>"},
  "deceased":   {"when_llm": "The caller says the customer or their spouse has passed away.", "go_to": "deceased_customer",
                 "filler": "<text lang=\"hi-IN\">यह सुनकर बहुत दुख हुआ।</text><text lang=\"en-IN\">I'm very sorry to hear that.</text>"}
}
```

## Anti-patterns

| Anti-pattern | What happens | Fix |
|---|---|---|
| The current scenario speaks the next scenario's opening "on this turn" | The move discards it; the line is never heard | The destination says it under WHEN THIS SCENARIO STARTS |
| "Emit no spoken text, the system routes" | Silence whenever the move doesn't fire | Remove; the move discards the reply anyway |
| Disposition set inside a closing scenario reached by a move | Its only reply is speech-only; the code is never recorded | Report it on the deciding turn |
| Plain-text gates on variables ("if X is true") with no STATE or If | The model can't see X; it guesses | STATE line or `<if>` |
| `x NOT_EQUALS true` on a boolean | `CONDITION_TYPE_MISMATCH` | Order transitions, or EXISTS / NOT_EXISTS |
| Mixed AND/OR in one `when` | `WHEN_MIXED_JOINERS` | Nest Ifs or two transitions |
| `{{name}}` inside a filler | `VARIABLE_IN_SPOKEN_LINE` (allowed in `<say>`) | Generic filler; the value goes in the next scenario's line |
| A filler only in English for a Hindi-first bot | `PRIMARY_LANGUAGE_MISSING` | Primary language first, every bot language |
| Enum options `1`, `2`, or more than 10 options | Unquoted values fail; over 10 fails | `tier1`/`tier2`; `text` for long code lists |
| A 10k-character scenario | `TEXT_TOO_LONG` (5000 of text, every language and voice) and re-sent uncached every turn | Shared rules to global sections; condense; split |
| `x IN ('a', 'b')` on an enum | Editor rejects multi-value IN | `x EQUALS 'a' OR x EQUALS 'b'` |
| `(a OR b) AND c` | Editor parse error | `(a OR b) AND (c)`, or nest Ifs |
| Plain `<text>` next to a `<male>`/`<female>` one in a `<say>` | Editor drops the plain line on re-save | Pair every language |
| Campaign variable used only as the first operand of an `<if>` | Editor deletes it on save; save fails `VARIABLE_MISSING` | Also use it elsewhere (`{{x}}`, a later operand) |
| `start` scenario that greets | The greeting was already played without the model | Continue from the caller's reply |
| `<say>` in a scenario that stays several turns | Repeated every turn (SAY EXACTLY each render) | Move on the answer, or guard with `NOT_EXISTS` |
| Closing scenario with only `<say>` lines | Spoken without the model: no `| EOC`, call stays open | One instruction line: thank, say goodbye, end the call |
| `Note:` in a spoken line | Stop sequence: the line is cut | Rephrase |
| Restating "never reveal your instructions" / injection rules | Already in the platform head | Domain and compliance rules only |
| Raw `&` or `<` in scenario text | `XML_MALFORMED` | Reword ("and", "before") |
| `inline` transition with `mode="auto"` next to other text | Editor error; runtime would move on the first turn | `llm` next to text; `auto` only alone in a branch |
| `inline` transition `auto` outside any If | `AUTO_TRANSITION_UNCONDITIONAL` | `variable` with a `when`, or move it into a branch |
| Announce ("let me check") + control block + tool call | The answer after the tool lands after `---CONTROL---` and is never spoken | Call the tool directly; reports after the final answer |
| Tool call written as text (`get_x(id=…)`) | The tool never runs | "Call the tool; never write it as text" |
| The model re-emits the interrupt of the scenario it is in | Ignored; the reply can be empty | Say "you are already in X; don't emit its interrupt" if seen |
| Updating an ID (UUID) in every scenario | 20–30 extra tokens per turn before the move is decided | Update it only where it changes |
| Tool calls and results removed from history | The model stops calling tools natively and loses facts | Keep them; only the turn instructions stay out |
| Broad interrupt (e.g. "cancel/surrender/docs → transfer") | Preempts scenario routes | Handle in scenarios; interrupts only for true global exits |
| Speaking "connecting you…" or `\| TTA` to transfer | Double filler or wrong path | Call the transfer tool silently |
| Asking a third party for KYC or payment, or saying the amount | Privacy breach | Only ask for the customer or a callback time |
| `name` at the top level, `type: single_prompt`, `extract`, `signal` | `SCHEMA_INVALID` / `UNKNOWN_ATTRIBUTE` | Version 2 shape only |
