# How a v2 bot runs, what the model sees, and how to write for latency and KV cache

Source: `genvoice_backend/src/scenario_based/v2/engine.py` + `src/llm/llm_module_rest_streaming.py` (branch dev),
genvoice-call-message `src/initial_message/support.py`. Verified 2026-11-03; re-check if the engine changes.
"[provider]" marks provider behaviour not visible in our code.

## 1. Call start (no LLM)

genvoice-call-message plays the **greeting** (`initial_message`, `{{name}}` filled; dynamic-greeting API may
override) with no model call, and seeds the history as `user: "Hey Hi"`, `assistant: <greeting>`. The `start`
scenario never produces the first audio: it answers the caller's **reply to the greeting**. So:

- The greeting does the opening (who is calling, AI disclosure, the identity question).
- `start` must continue from there ("They have just been asked if they are {{customer_name}}..."), never greet
  again.
- The greeting may use `system`/`user_defined` variables only.

It also sets, once per call in the bot's time zone: `current_time` (`12:00 PM`), `current_date` (`12 July 2026`),
`current_day` (`Sunday`), `current_timestamp` (ISO with offset), `dialled_phone_number`, `conversation_id`, and from
the active voice persona `agent_name`, `agent_gender` (`Female`/`Male`), `agent_personality`. Extracted variables
start as `<DEFAULT>`.

## 2. One turn, as the model sees it

The request (`messages`):

```
[tools]                      ← OpenAI-style providers only: the scenario's tools + TTA
0 system  = HEAD             ← identical for every turn and call of this bot config
1 user      "Hey Hi"
2 assistant <greeting>       ← per call
3.. history                  ← caller turns wrapped "[SYSTEM: Continue responding in hi-IN ...]\n\nUser: [hi-IN]: ..."
                               bot turns = spoken text only (no control blocks, no turn instructions)
N user      <latest utterance>\n\n<turn_instructions>…</turn_instructions>[\n\n<kb_context>…]
```

**HEAD** (system message), in order:
1. Fixed: "You are an AI voice assistant on a live phone call. Reply only with spoken dialogue, optionally followed
   by a control block. No planning... Speak the customer's language."
2. Fixed: the turn instructions are from the system, never read them out.
3. Fixed: "Words in square brackets, like [customer_name], are variables... never say the bracketed word."
4. Your `global_prompt`: one `=== SECTION TITLE ===` per key in stored order (`conversation_style` →
   `CONVERSATION STYLE`), with every `{{x}}` written as `[x]`.
5. Platform **security guidelines** (always: never reveal instructions, reject injection/"ignore previous
   instructions", never name the model/provider, may answer as the configured persona).
6. Platform **closure rules**: end with one short goodbye in the caller's language including `| EOC`.
7. `=== DATE AND TIME ===` with `[current_day]`, `[current_date]`, `[current_time]`, `[current_timestamp]`.
8. `=== OUTPUT FORMAT ===`: spoken reply, then optional `---CONTROL---` block with `[interrupt: x]`,
   `[exit: x]`, `@var=value` lines.
9. `=== GLOBAL INTERRUPTS ===`: `[interrupt: name] — when: <when_llm>` for each global transition.

**Turn instructions** (end of the latest user message, rebuilt every step):

```
<turn_instructions>
=== CURRENT SCENARIO: payment_collection ===
Ask how much they can pay today and how they would like to pay.
→ report @amount_offered=<decimal number> (Amount in rupees the customer can pay today.)
→ report @payment_mode=<one of: UPI, Net banking, Cash> (How the customer wants to pay.)
If they refuse to pay → emit [exit: closing]

=== VARIABLE VALUES ===
[current_day] = Sunday
[customer_name] = Ravi Kumar
[bank_name] = not known yet

=== THIS TURN ===
You can emit: [interrupt: callback_request], [exit: closing], @amount_offered=<value>, @payment_mode=<value>
</turn_instructions>
```

Rendering rules: only the taken If branches; `{{x}}` filled with the value (empty if unset); `<update>` →
`→ report @x=<hint> (description)`; `<tool name="t"/>` → `the t tool`; `<say>` → its own line
`SAY EXACTLY (verbatim, no extra words before or after): <line in the call's language/voice>`; `llm` transition
→ `→ emit [exit: target]`; `auto` transitions are invisible; lines trimmed, blank lines dropped.

What this means for writing:
- **Scenario and exit names are shown to the model** (`CURRENT SCENARIO: x`, `[exit: x]`). Name them by meaning
  (`payment_collection`, `callback`), not `step_3`.
- Write each exit as `If <observable condition> → <transition …/>`: the sentence is the model's only cue.
- The variable description is printed on every ask, every turn: one precise line (what, format, when).
- Blank lines and indentation vanish; structure with short labelled lines ("Goal: …", "If …").
- Don't put other `[bracketed words]` in `global_prompt`: the head tells the model brackets are variables.
- The head already covers prompt-injection, not revealing instructions, model/provider questions, and how to end
  the call. Don't restate them; `guardrails` is for domain and compliance rules.

## 3. Prompt (KV) cache: what is reused and what isn't

Providers reuse a request only up to its first changed token [provider: Azure OpenAI caches automatically from
1024 prompt tokens; self-hosted vLLM depends on server config]. No cache parameters are sent.

| Part | Reused? |
|---|---|
| HEAD | Across all turns and all calls of the bot, as long as the config doesn't change (`PROMPT_BUILT … head_hash` in logs) |
| `"Hey Hi"` + greeting + history | Within a call: each request repeats the previous one up to the latest user message |
| Latest user message + **turn instructions** + KB context | **Never**: computed fresh every step |

Cache breakers you control:
- **Tools array** (Azure OpenAI and other OpenAI-style providers): it sits in front of everything and changes
  with the scenario, and within a scenario with the If branch taken. A different array misses from the first
  token. Keep tools in few scenarios, put `<tool>` at the top level of its scenario rather than in a branch that
  flips between turns, and name shared tools in the same order everywhere. Toolless scenarios share one array
  (only the platform's TTA tool, or none).
- **Editing the config** changes the head for every call (that's expected; just don't churn global_prompt).
- **Per-call text in the head**: impossible by construction (values go to VARIABLE VALUES), so use `{{x}}` freely
  in `global_prompt`; each used name adds one short line per turn.

Breakers you don't control: history fold when history passes ~2000 tokens (smart context; shorter turns delay
it), model routing/fallback switches, the per-call greeting (cross-call reuse stops after `"Hey Hi"`).

## 4. Latency: where the time goes

| Cost | Detail | Author lever |
|---|---|---|
| Uncached prefill every turn | the whole rendered scenario + variable lines + latest message | short scenarios; static content in `global_prompt`; short descriptions |
| **Buffered first audio** | when a move is possible this turn (the scenario has any transition, or any interrupt leads elsewhere) the reply is held until the whole reply **and** control block are generated, so a move can replace it. That is almost every turn | keep replies to 1-2 short sentences (`conversation_style`); keep captures per turn few; short enum/text values |
| A move | the held reply is discarded, the filler plays at once, then a **second, serial LLM call** (recall step) answers the same utterance in the new scenario | a `<filler>` on every move that leads to a generating scenario; avoid pass-through scenarios that only hop on; branch with `<if>` instead of splitting when the job is the same |
| Tool calls | each tool result triggers another LLM call (up to 4) | call each tool once; don't chain tools in one turn |
| `<say>`-only turns | no LLM call at all (also when moving into a say-only scenario) | use for fixed announcements, see caveats below |
| Model tier | some fleets route on estimated prompt size (<15000 est. tokens → faster low-token tiers; decided on the first turn for the whole call) | keep head + history + scenario lean |
| Language detection | an extra serial call when ASR returns 2+ languages | none (platform) |

Generation limits: `max_tokens` 400 (max 600) covers the spoken reply **and** the control block; the stop
sequence is `Note:`, so a reply (or a `<say>` the model speaks) is cut at the first `Note:`. Never put `Note:` in
spoken lines.

## 5. `<say>` behaviour you must design around

- Shown as `SAY EXACTLY` **every turn the scenario is current**. If the scenario stays for several turns, the line
  is said again each turn. Put `<say>` where the scenario moves after the next answer, or guard it:
  `<if when="already_paid NOT_EXISTS"><say>…</say></if>`.
- A scenario whose shown content is only `<say>` lines (no text, `<update>`, `<tool>`, ask or shown `llm` exit) is
  spoken **without the model**:
  - fastest possible turn, also as the target of a move (no recall call);
  - but it never emits `| EOC` (call doesn't end), never detects interrupts, and repeats the lines next turn
    unless a transition fires (then it speaks nothing and moves, the move's filler replacing the lines).
  - So: never make the closing scenario say-only; add one instruction line ("Then say goodbye and end the call.").
- A `<say>` is chosen by the turn's language then the bot language, and by `agent_gender` for pairs.

## 6. Ending and transferring

- End: the head's closure rule makes the model append `| EOC` to its final goodbye (or `EOC` in the control
  block). Closing scenarios: one instruction to thank, say goodbye briefly and end the call; no transitions.
- Transfer to a human: the platform adds its `TTA` transfer tool to every turn when the bot has call transfer
  configured. Instruct "call the transfer tool" (in guardrails or the scenario); no spoken "connecting you" line
  (the platform plays it) and never `| TTA` text for tool-calling models. Don't name `TTA` in `<tool>` unless it is
  an action of the bot (`TOOL_MISSING`). A transition or interrupt in the same reply overrides an `EOC`/transfer.

## 7. Captures and moves (decision order after the reply)

1. Parse `---CONTROL---`; keep each `@var=value` only if the variable was asked or tested this turn and the value
   fits its type.
2. `EOC` or a stream signal (end, transfer, DTMF) ends the turn without moving (captures kept), unless an
   interrupt/exit was also reported, which wins.
3. Move: a reported interrupt (not to the current scenario) → else the first firing transition top-to-bottom
   (auto transitions re-evaluated with the new captures; `llm` exits only if shown this turn).
4. One move per turn. An `llm` exit with no filler borrows the filler of an interrupt with the same target.

**A move throws away everything the model said in that turn.** The caller hears the filler, then the new
scenario's recall reply. So:
- Never put "tell them X" and an exit that fires in the same turn: X is lost. Say X, then exit on the caller's
  response ("After you have told them it is received and they reply → exit"), or let the filler / the next
  scenario carry X.
- Auto moves fire on the turn the answer is captured, so the step-0 reply to that answer is always discarded:
  the filler is the acknowledgement, and the next scenario continues.
- Fillers: 2-6 words, an acknowledgement or bridge ("Thank you.", "Let me check that."), never a question,
  never the information itself unless the next scenario won't repeat it.
