# How a version 2 call runs, and what it means for authoring

Read this when designing moves, fillers, state and tool use. The behaviour below is what the runtime does today;
the best practices at the end follow from it and from real test calls.

## 1. What the model receives every turn

**Head** (the system message; identical for every turn and every call of a bot, so the provider can cache it):
fixed instructions, the global prompt sections in stored order (`{{name}}` shown as `[name]`), security and closing
rules, a date-and-time line, the reply format (below) and every global interrupt with its `when_llm`.

**Turn instructions**, rebuilt every turn and appended to the customer's latest message (never stored in the
conversation history):

```
=== CURRENT SCENARIO: <name> ===
<the scenario, rendered>
=== VARIABLE VALUES ===
[customer_name] = Ravi Kumar          ← only names used in the head, plus the date and time variables
=== THIS TURN ===
You can emit: [interrupt: talk_to_human], [exit: callback], @identity_confirmed=<value>
```

How a scenario is rendered:

| In the scenario | The model sees |
|---|---|
| Text | The text, with `{{name}}` replaced by the value (or nothing) |
| `<update var="x"/>` | `→ report @x=<hint> (description)` at that spot |
| `<tool name="x"/>` | `the x tool` (and the tool is offered) |
| `<say>` | `SAY EXACTLY (verbatim, no extra words before or after): <line for the call's language and voice>` |
| `inline` `llm` transition | `→ emit [exit: <go_to>]` |
| `auto` transitions | Nothing (the runtime moves by itself) |
| An If | Only the taken branch's body. A waiting If shows nothing and asks for its missing variables |

**The model only sees values that are shown**: `[name]` values listed under VARIABLE VALUES, and `{{name}}`
filled into the scenario text. A sentence like "if tier1_offer_delivered is true…" does not show the value. Make
decisions visible with a STATE line (`STATE: tier1_offer_delivered={{tier1_offer_delivered}}`) or move the decision
into `<if when="…">`.

## 2. What the model writes

```
<spoken reply>
---CONTROL---
[interrupt: talk_to_human]
[exit: callback]
@identity_confirmed=true
```

- The spoken reply comes first. The control block is optional and only for reports.
- **Everything after `---CONTROL---` is never spoken.** If the model writes its answer after the block, the caller
  never hears it. This happens when a model announces a lookup ("let me check"), writes a control block, calls a
  tool and only then answers — instruct tool-using scenarios accordingly (§6).
- A report is kept only if the variable is reportable in this scenario (named by an `<update>`, tested by a
  condition, or asked by a waiting If) and fits its type.
- A closing line ends with `| EOC`; the call ends after it is spoken.

## 3. Moves

1. The runtime captures this turn's reports.
2. A reported interrupt moves the call, unless it leads to the current scenario.
3. Otherwise the first transition that fires, in written order: an `auto` transition whose `when` holds or whose
   branch is taken; an `llm` exit that the model reported and that was shown before and after the captures.
4. **One move per turn.**

While a move is possible this turn (an interrupt is allowed or the scenario has a transition), the reply is
**held** until the decision. On a move the held reply is discarded: the caller hears the transition's filler (if
any) and then the next scenario's answer. Otherwise the held reply is spoken.

**The first reply after a move**: the destination scenario answers the **same** customer turn at once. In that
reply the model may speak and call the scenario's tools, but **it cannot report variables or move** (no control
block). Its own transitions are judged from the customer's next turn. The filler just spoken is the last assistant
message the model sees.

Say-only scenarios (everything shown is `<say>`) are spoken without calling the model.

## 4. Conversation history

Stored per turn: the customer's message, the model's tool calls and tool results, and one assistant reply with
everything spoken in the turn (filler included). The turn instructions are never stored. Tool results stay in the
history, so later turns can use them.

## 5. Languages, voices, time

- A line is picked for the call's current language, else the bot's primary language (exact code before base
  language, else the first line).
- `<male>`/`<female>` follow the voice gender set at call start (`agent_gender`); anything but male uses female.
- The date and time variables are set once at call start; the model is told to treat them as now.

## 6. Best practices that follow (each one fixed a real failure)

1. **Speak a scenario's opening in that scenario.** On a move the current reply is discarded, so a line the
   current scenario says "for" the next one is never heard. Put it under "WHEN THIS SCENARIO STARTS" in the
   destination.
2. **Report outcomes on the deciding turn.** Dispositions and other outcome flags must be reported together with
   the flag that triggers the move; the next scenario's first reply can't report anything. A closing scenario
   entered by a move ends the call in that first reply.
3. **"Line already said" flags are reported a turn later.** If a line is said in a first reply, report its flag on
   the next turn ("including when it was said as this scenario started"). Don't gate a move on such a flag when the
   flow already guarantees the order — just move on the customer's response.
4. **Never instruct "say nothing" or "emit no spoken text".** If the expected move doesn't happen, the caller gets
   silence. Let the move discard the reply instead.
5. **Show what the model must decide on** (STATE line or `<if>`). Prefer `<if>` for deterministic branching; it
   also hides the other branches.
6. **Ask, then branch, in one scenario** with a waiting If: put the question in the text and branch on the answer;
   the If waits until the answer arrives and moves in that turn.
7. **Global interrupts preempt scenario routes.** Use them only for true "from anywhere" exits (busy, abuse/DND,
   distress, death, talk to a human when that needs a scenario). A broad interrupt (e.g. "anything about
   cancellation → transfer") fires before the scenario's own handling.
8. **Interrupt to the current scenario is ignored.** Still, models tend to re-emit the interrupt of the scenario
   they are in; say so in the scenario if it keeps happening.
9. **Tool scenarios**: tell the model to call the tool directly when it needs data (no "let me check" line before
   it), to answer from the result, and to put reports only after the final answer. Never write a tool call as
   text. Keep tool calls and results in history (don't remove them).
10. **Don't make the model re-report stable values every turn** (IDs, UUIDs): every reported character delays the
    end of the turn. Update such a variable only where it can change.
11. **Keep instructions consistent with the first reply after a move.** "Call the tool first, also right after a
    move" plus a speech-only first reply leads the model to announce instead of answer. Prefer "answer from the
    tool result; call the tool if you don't have it".
12. **Fillers**: short (2 to 6 words), natural, primary language first, all bot languages, no `{{name}}`. They
    replace the discarded reply, so they must make sense before the next scenario's line. Leave a filler out where
    the script forbids an acknowledgement (e.g. before a scripted empathy line).
13. **Verbatim lines once**: scripted lines are said once per call; say so, and give the short re-ask to use
    instead of repeating them.
14. **The transfer-to-agent tool is always available**: transfer by calling it, without a spoken "connecting you"
    line (the platform plays its own), and never by writing `| TTA` in speech.

## 7. Call start

genvoice-call-message plays the greeting (`initial_message`, values filled in) **without the model**, and seeds the
history as `user: "Hey Hi"`, `assistant: <greeting>`. The `start` scenario therefore answers the caller's reply to
the greeting; it never greets again. The greeting may use `system`/`user_defined` variables only. Call-message also
sets, once per call in the bot's time zone, `current_time` (`12:00 PM`), `current_date` (`12 July 2026`),
`current_day`, `current_timestamp` (ISO with offset), `dialled_phone_number`, `conversation_id`, and from the active
voice persona `agent_name`, `agent_gender` (`Female`/`Male`) and `agent_personality`. Extracted variables start as
`<DEFAULT>`.

The head already contains the platform's security guidelines (never reveal instructions, reject prompt injection,
never name the model or provider) and closure rules (one short goodbye ending in `| EOC`). Don't restate them in the
global prompt: `guardrails` is for domain and compliance rules. The head also tells the model that words in square
brackets are variables, so avoid other `[bracketed words]` in the global prompt. Scenario names and exit targets are
shown to the model (`CURRENT SCENARIO: x`, `[exit: x]`): name them by meaning.

## 8. `<say>` caveats

- A `<say>` is shown as SAY EXACTLY on **every** turn its scenario is current. Use it where the scenario moves on the
  next answer, or guard it with `<if when="x NOT_EXISTS">` on a variable set right after it.
- A scenario whose shown content is only `<say>` lines is spoken without the model (also when it is the target of a
  move, so no extra call). It then **never ends the call** (no `| EOC`), catches no interrupt, and repeats on the next
  turn unless a transition fires. Never make a closing scenario say-only; give it one instruction line.
- The model's stop sequence is `Note:`: a line the model speaks is cut there. Never put `Note:` in spoken lines.
- `max_tokens` is 400 (at most 600) for the spoken reply **and** the control block together.

## 9. Latency and prompt (KV) cache

The request each turn: `[tools]` (OpenAI-style providers) · head · `"Hey Hi"` · greeting · history · latest
customer message + turn instructions (+ knowledge-base context). Providers reuse a request only up to its first
changed token (Azure OpenAI caches automatically from 1024 prompt tokens; self-hosted servers depend on their
config). No cache parameters are sent.

| Part | Reused |
|---|---|
| Head (fixed rules, global prompt, interrupts) | Across all turns and calls of the bot while the config is unchanged (`PROMPT_BUILT … head_hash` in logs) |
| Greeting and history | Within a call: each request repeats the previous one up to the latest customer message |
| Latest message + turn instructions (rendered scenario, variable values, THIS TURN) | Never: computed every turn |

| Cost | Where it comes from | Lever |
|---|---|---|
| Uncached prefill every turn | the rendered scenario, every shown description, the VARIABLE VALUES lines | short scenarios; static content in global prompt sections; one-line descriptions |
| First audio waits for the whole reply | while a move is possible (almost every turn) the reply and its control block are generated in full before anything is spoken | replies of 1-2 short sentences; few reports per turn; short values |
| A move | the held reply is discarded, the filler plays, then a **second serial LLM call** answers in the new scenario | fillers on moves; no pass-through scenarios that only hop on; branch with `<if>` when the job is the same |
| Tools | each tool result triggers another model call (up to 4) | call once; no chains in one turn |
| Tools array changes | the scenario's tools (plus TTA) are sent per turn, in first-use order; a different array misses the cache from the first token on OpenAI-style providers | tools in few scenarios; at the scenario's top level unless a branch must hide them; shared tools named in the same order |
| Model tier | some fleets route on estimated prompt size (under ~15000 estimated tokens → faster tiers, decided on the first turn for the whole call) | keep head + history + scenario lean |

**`<if>` and the cache.** An If costs nothing for the cache: the head never contains scenario text, and the runtime
renders only the taken branch into the turn instructions, which are uncached anyway. The conditions and untaken
branches never reach the model. So branching with `<if>` *reduces* per-turn tokens compared with prose
("if premium, say X; if standard, say Y; …"), and it is deterministic. Measured on `assets/example_emi_v2.json`:
the 1,307-character `payment_plan` string renders as 483 characters; `emi_reminder` renders 388 characters for
`risk_band = low` and 493 for `high`. The one If-related cache cost is a `<tool>` inside a branch (the tools array).

**Global prompt variables and VARIABLE VALUES.** Every `{{x}}` used in the head adds a `[x] = value` line to every
turn's turn instructions, in every scenario, on top of the four date and time lines. A `{{x}}` used only in a
scenario is filled inline there and costs nothing elsewhere. In the example the VARIABLE VALUES block (~11 lines)
is larger than most scenarios' text. Reference a per-call value in the global prompt only when most scenarios need
it (who the customer is, the product); put step-specific values (amounts, dates, IDs) in the scenarios that use them.

Example budget (real runtime): head 6,338 characters (~1,760 tokens), identical across customers and turns; turn
instructions 600-1,045 characters per turn.

Things outside the author's control also break the cache: the per-call greeting (cross-call reuse stops after the
head), history folding once it passes ~2000 tokens, and model fallbacks.
