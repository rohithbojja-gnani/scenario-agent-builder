#!/usr/bin/env python3
"""Self-check for validate_v2.py: python3 scripts/test_validate_v2.py

The example bot must be clean; each mutation must raise exactly the listed codes. Backend codes were confirmed
against genvoice_backend_v1's own validator (main/scenario_v2) on 2026-11-03."""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from validate_v2 import validate  # noqa: E402

BOT = json.load(open(os.path.join(HERE, "..", "assets", "example_emi_v2.json"), encoding="utf-8"))
LANGS, TOOLS = BOT["bot_language"], ["check_payment_status", "send_payment_link"]


def add(text, scenario="closing"):
    def mutate(c):
        c["scenarios"][scenario] += "\n" + text
    return mutate


def put(path, value):
    def mutate(c):
        obj = c
        for key in path[:-1]:
            obj = obj[key]
        obj[path[-1]] = value
    return mutate


EN_HI = '<text lang="en-IN"><male>Hi</male><female>Hi</female></text><text lang="hi-IN"><male>हाय</male><female>हाय</female></text>'
CASES = {  # name: (mutation, expected error codes, expected warning codes)
    "bare ampersand": (add("Explain the T&C."), {"XML_MALFORMED"}, set()),
    "unknown tag": (add("<note>x</note>"), {"UNKNOWN_ELEMENT"}, set()),
    "signal attribute": (add('<transition type="inline" go_to="callback" mode="llm" signal="TTA"/>'), {"UNKNOWN_ATTRIBUTE"}, {"LINT_NO_FILLER"}),
    "comment": (add("<!-- x -->"), {"COMMENT_NOT_ALLOWED"}, set()),
    "words in say": (add("<say>Hello.</say>"), {"MISPLACED_ELEMENT", "PRIMARY_LANGUAGE_MISSING"}, {"LINT_LANGUAGE_MISSING"}),
    "undeclared var": (add("Thank {{customer_nme}}."), {"VARIABLE_MISSING"}, set()),
    "system update": (add('<update var="current_date"/>'), {"SYSTEM_VARIABLE_UPDATE"}, set()),
    "unknown tool": (add('<tool name="refund"/>'), {"TOOL_MISSING"}, set()),
    "auto at top level": (add('<transition type="inline" go_to="callback" mode="auto"/>'), {"AUTO_TRANSITION_UNCONDITIONAL"}, {"LINT_NO_FILLER"}),
    "llm with when": (add('<transition type="variable" go_to="callback" mode="llm" when="already_paid EQUALS true"/>'), {"LLM_TRANSITION_WITH_WHEN"}, {"LINT_NO_FILLER"}),
    "self transition": (add('<transition type="inline" go_to="closing" mode="llm"/>'), {"SELF_TRANSITION"}, {"LINT_NO_FILLER"}),
    "auto beside text": (add("<if when=\"risk_band EQUALS 'low'\">Say hi.<transition type=\"inline\" go_to=\"callback\" mode=\"auto\"/></if>"), {"TRANSITION_MODE_MISMATCH"}, {"LINT_NO_FILLER"}),
    "jinja": (add("{% if customer_name %}Hi{% endif %}"), {"TEMPLATE_NOT_ALLOWED"}, set()),
    "unquoted string": (add("<if when=\"risk_band EQUALS high\">x</if>"), {"WHEN_SYNTAX"}, set()),
    "mixed joiners": (add("<if when=\"risk_band EQUALS 'a' AND risk_band EQUALS 'b' OR risk_band EQUALS 'c'\">x</if>"), {"WHEN_MIXED_JOINERS"}, set()),
    "quoted boolean": (add("<if when=\"already_paid EQUALS 'true'\">x</if>"), {"CONDITION_TYPE_MISMATCH"}, {"LINT_NO_ESCAPE"}),
    "text comparison": (add("<if when=\"emi_amount GREATER_THAN 4000\">x</if>"), {"CONDITION_TYPE_MISMATCH"}, set()),
    "enum not allowed": (add("<if when=\"payment_mode EQUALS 'cheque'\">x</if>"), {"CONDITION_TYPE_MISMATCH"}, {"LINT_NO_ESCAPE"}),
    "var in filler": (put(["global_transitions", "stop_calling", "filler"], EN_HI.replace("Hi<", "Hi {{customer_name}}<", 1)), {"VARIABLE_IN_SPOKEN_LINE"}, set()),
    "primary missing": (add('<say><text lang="hi-IN"><male>हाय</male><female>हाय</female></text></say>'), {"PRIMARY_LANGUAGE_MISSING"}, set()),
    "half pair": (add('<say><text lang="en-IN"><male>Hi</male></text><text lang="hi-IN"><male>हाय</male><female>हाय</female></text></say>'), {"VOICE_PAIR_INCOMPLETE"}, set()),
    "link": (add("Visit www.example.com."), {"LINK_NOT_ALLOWED"}, set()),
    "long scenario": (add("x" * 5001), {"TEXT_TOO_LONG"}, {"LINT_SCENARIO_LONG"}),
    "markup in prompt": (put(["global_prompt", "guardrails"], "<Security Guidelines> no"), {"MARKUP_IN_GLOBAL_PROMPT"}, set()),
    "v1 field": (put(["global_transitions", "stop_calling", "deterministic_exit_cue"], {"en-IN": "x"}), {"SCHEMA_INVALID"}, set()),
    "scenario object": (put(["scenarios", "closing"], {"prompt": "x"}), {"SCHEMA_INVALID"}, set()),
    "one enum value": (put(["variables_schema", "payment_mode", "allowed_values"], ["upi"]), {"INVALID_ALLOWED_VALUES", "CONDITION_TYPE_MISMATCH"}, set()),
    "FE multi IN": (add("<if when=\"payment_mode IN ('upi', 'branch_cash')\">x</if>"), {"FE_IN_LIST"}, {"LINT_NO_ESCAPE"}),
    "FE enum case": (add("<if when=\"payment_mode EQUALS 'UPI'\">x</if>"), {"FE_ENUM_CASE"}, {"LINT_NO_ESCAPE"}),
    "FE brackets": (add("<if when=\"(risk_band EQUALS 'a' OR risk_band EQUALS 'b') AND loan_id EXISTS\">x</if>"), {"FE_BRACKETS"}, set()),
    "FE empty else": (add("<if when=\"risk_band EQUALS 'a'\">x</if><else></else>"), {"FE_EMPTY_BRANCH"}, {"EMPTY_BRANCH"}),
    "FE mixed voices": (add('<say><text lang="en-IN">Hi</text><text lang="hi-IN"><male>हाय</male><female>हाय</female></text></say>'), {"FE_MIXED_VOICES"}, set()),
    "FE pruned var": (lambda c: (c["variables_schema"].__setitem__("segment", {"source": "user_defined", "type": "text", "description": "x"}),
                                 add("<if when=\"segment EQUALS 'gold'\">Thank them.</if>")(c)), {"FE_VARIABLE_PRUNED"}, set()),
    "say-only closing": (put(["scenarios", "wrong_person"], "<say>" + EN_HI + "</say>"), set(), {"LINT_SAY_ONLY"}),
    "stop word": (add('<say><text lang="en-IN"><male>Note: hi</male><female>Note: hi</female></text><text lang="hi-IN"><male>हाय</male><female>हाय</female></text></say>'), set(), {"LINT_STOP_WORD"}),
}


def main():
    cfg = BOT["scenario_config"]
    rep = validate(cfg, LANGS, TOOLS, BOT["initial_message"])
    failures = [f"example not clean: {rep.errors + rep.warnings}"] if rep.errors or rep.warnings else []
    for name, (mutate, want_errors, want_warnings) in CASES.items():
        c = copy.deepcopy(cfg)
        mutate(c)
        rep = validate(c, LANGS, TOOLS, BOT["initial_message"])
        got = ({e[0] for e in rep.errors}, {w[0] for w in rep.warnings})
        if got != (want_errors, want_warnings):
            failures.append(f"{name}: want {want_errors} {want_warnings}, got {got[0]} {got[1]}")
    print("\n".join(failures) or f"ok: example clean, {len(CASES)} cases pass")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
