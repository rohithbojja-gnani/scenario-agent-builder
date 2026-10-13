#!/usr/bin/env python3
"""Offline checker for scenario_config version 2.

Usage:
  python3 scripts/check_v2.py config.json [--languages hi-IN,en-IN] [--tools tool_a,tool_b]

The file may hold the scenario_config itself, a bot_config with "scenario_config", or {"scenario_config": ...}.
--languages: the bot's languages, primary first (enables the language rules).
--tools: the bot's action names (enables the tool check).
Exit code 1 when there are errors. Standard library only.
"""
import argparse
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET

NAME = re.compile(r"^[a-z぀-ヿ一-鿿][a-z0-9_぀-ヿ一-鿿]{2,63}$")
TOP_KEYS = {"version", "start", "global_prompt", "variables_schema", "global_transitions", "scenarios"}
CORE_PROMPT = ("persona", "context", "guardrails")
SOURCES = {"system", "user_defined", "extracted"}
TYPES = {"text", "number", "decimal", "boolean", "enum"}
TAGS = {"update", "tool", "say", "transition", "filler", "text", "male", "female", "if", "elif", "else"}
BODY_TAGS = {"update", "tool", "say", "transition", "if", "elif", "else"}
ATTRS = {
    "update": ({"var"}, set()), "tool": ({"name"}, set()), "say": (set(), set()),
    "transition": ({"type", "go_to", "mode"}, {"when"}), "filler": (set(), set()), "text": ({"lang"}, set()),
    "male": (set(), set()), "female": (set(), set()), "if": ({"when"}, set()), "elif": ({"when"}, set()),
    "else": (set(), set()),
}
OPERATORS = {"EQUALS", "NOT_EQUALS", "GREATER_THAN", "GREATER_OR_EQUAL", "LESS_THAN", "LESS_OR_EQUAL", "IN", "NOT_IN", "EXISTS", "NOT_EXISTS"}
ALLOWED_OPS = {
    "text": {"EQUALS", "NOT_EQUALS", "EXISTS", "NOT_EXISTS"},
    "number": {"EQUALS", "NOT_EQUALS", "GREATER_THAN", "GREATER_OR_EQUAL", "LESS_THAN", "LESS_OR_EQUAL", "EXISTS", "NOT_EXISTS"},
    "decimal": {"EQUALS", "NOT_EQUALS", "GREATER_THAN", "GREATER_OR_EQUAL", "LESS_THAN", "LESS_OR_EQUAL", "EXISTS", "NOT_EXISTS"},
    "boolean": {"EQUALS", "EXISTS", "NOT_EXISTS"},
    "enum": {"EQUALS", "NOT_EQUALS", "IN", "NOT_IN", "EXISTS", "NOT_EXISTS"},
}
MARKUP = re.compile(r"</?(update|tool|say|transition|filler|text|male|female|if|elif|else)\b")
TEMPLATE = re.compile(r"\{\{(.*?)\}\}|\{%|\{#|\{\{")
NUMBER = re.compile(r"^-?\d+(\.\d+)?$")
MAX_SCENARIO, MAX_PROMPT, MAX_TEXT, NEAR = 5000, 3000, 1000, 4800


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

    def error(self, code, path, message):
        self.errors.append((code, path, message))

    def warn(self, code, path, message):
        self.warnings.append((code, path, message))


def load(path):
    data = json.load(open(path, encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("scenario_config"), dict):
        return data["scenario_config"]
    return data


def prompt_chars(value):
    return len(value.replace("\n", "").replace("\r", ""))


def check_schema(config, report):
    if not isinstance(config, dict):
        report.error("SCHEMA_INVALID", "(root)", "The config must be a JSON object.")
        return
    for key in set(config) - TOP_KEYS:
        report.error("SCHEMA_INVALID", key, f"Unknown top-level key '{key}'.")
    for key in ("version", "start", "global_prompt", "scenarios"):
        if key not in config:
            report.error("SCHEMA_INVALID", key, f"'{key}' is required.")
    if "version" in config and (config["version"] != 2 or isinstance(config["version"], bool)):
        report.error("SCHEMA_INVALID", "version", "version must be the integer 2.")
    if "start" in config and not (isinstance(config["start"], str) and NAME.match(config["start"])):
        report.error("SCHEMA_INVALID", "start", "start must be a valid scenario name.")
    prompt = config.get("global_prompt")
    if "global_prompt" in config:
        if not isinstance(prompt, dict):
            report.error("SCHEMA_INVALID", "global_prompt", "global_prompt must be an object.")
        else:
            style = prompt.get("conversation_style", prompt.get("conversationStyle"))
            for key, value in [(k, prompt.get(k)) for k in CORE_PROMPT] + [("conversation_style", style)]:
                if not (isinstance(value, str) and value.strip()):
                    report.error("SCHEMA_INVALID", f"global_prompt.{key}", f"global_prompt.{key} is required and non-empty.")
            for key, value in prompt.items():
                if key not in CORE_PROMPT + ("conversation_style", "conversationStyle") and not NAME.match(key):
                    report.error("SCHEMA_INVALID", f"global_prompt.{key}", f"Invalid section name '{key}'.")
                if not isinstance(value, str):
                    report.error("SCHEMA_INVALID", f"global_prompt.{key}", "Sections must be strings.")
                elif prompt_chars(value) > MAX_PROMPT:
                    report.error("SCHEMA_INVALID", f"global_prompt.{key}", f"{prompt_chars(value)} characters without newlines; the limit is {MAX_PROMPT}.")
    variables = config.get("variables_schema", {})
    if not isinstance(variables, dict):
        report.error("SCHEMA_INVALID", "variables_schema", "variables_schema must be an object.")
    else:
        if len(variables) > 100:
            report.error("SCHEMA_INVALID", "variables_schema", f"{len(variables)} variables; the limit is 100.")
        for name, var in variables.items():
            path = f"variables_schema.{name}"
            if not NAME.match(name):
                report.error("SCHEMA_INVALID", path, f"Invalid variable name '{name}'.")
            if not isinstance(var, dict):
                report.error("SCHEMA_INVALID", path, "A variable must be an object.")
                continue
            for key in set(var) - {"source", "type", "description", "allowed_values"}:
                report.error("SCHEMA_INVALID", f"{path}.{key}", f"Unknown key '{key}'.")
            if var.get("source") not in SOURCES:
                report.error("SCHEMA_INVALID", f"{path}.source", "source must be system, user_defined or extracted.")
            if var.get("type") not in TYPES:
                report.error("SCHEMA_INVALID", f"{path}.type", "type must be text, number, decimal, boolean or enum.")
            if var.get("source") in ("system", "user_defined") and var.get("type") != "text":
                report.error("SCHEMA_INVALID", f"{path}.type", "system and user_defined variables must be text.")
            if not isinstance(var.get("description", ""), str) or len(var.get("description", "")) > 256:
                report.error("SCHEMA_INVALID", f"{path}.description", "description must be a string of at most 256 characters.")
            if var.get("type") == "enum" and not isinstance(var.get("allowed_values"), list):
                report.error("SCHEMA_INVALID", f"{path}.allowed_values", "An enum needs allowed_values.")
            if var.get("type") != "enum" and "allowed_values" in var:
                report.error("SCHEMA_INVALID", f"{path}.allowed_values", "Only an enum can have allowed_values (not even null).")
    interrupts = config.get("global_transitions", {})
    if not isinstance(interrupts, dict):
        report.error("SCHEMA_INVALID", "global_transitions", "global_transitions must be an object.")
    else:
        if len(interrupts) > 50:
            report.error("SCHEMA_INVALID", "global_transitions", "At most 50 global transitions.")
        for name, item in interrupts.items():
            path = f"global_transitions.{name}"
            if not NAME.match(name):
                report.error("SCHEMA_INVALID", path, f"Invalid interrupt name '{name}'.")
            if not isinstance(item, dict) or set(item) - {"when_llm", "go_to", "filler"} or not {"when_llm", "go_to"} <= set(item):
                report.error("SCHEMA_INVALID", path, "A global transition is exactly {when_llm, go_to, filler?}.")
                continue
            for key in ("when_llm", "filler"):
                if key in item and not (isinstance(item[key], str) and 1 <= len(item[key]) <= MAX_TEXT):
                    report.error("SCHEMA_INVALID", f"{path}.{key}", f"{key} must be 1 to {MAX_TEXT} characters.")
    scenarios = config.get("scenarios")
    if "scenarios" in config:
        if not isinstance(scenarios, dict) or not 1 <= len(scenarios) <= 100:
            report.error("SCHEMA_INVALID", "scenarios", "scenarios must be an object with 1 to 100 entries.")
        else:
            for name, source in scenarios.items():
                if not NAME.match(name):
                    report.error("SCHEMA_INVALID", f"scenarios.{name}", f"Invalid scenario name '{name}'.")
                if not (isinstance(source, str) and 1 <= len(source) <= MAX_SCENARIO):
                    report.error("SCHEMA_INVALID", f"scenarios.{name}", f"A scenario is a string of 1 to {MAX_SCENARIO} characters (this one: {len(source) if isinstance(source, str) else type(source).__name__}).")


def is_letterish(char):
    return char in " _-" or unicodedata.category(char)[0] in "LMN"


def check_variables(variables, report):
    for name, var in variables.items():
        if var.get("type") != "enum":
            continue
        values, path = var.get("allowed_values") or [], f"variables_schema.{name}.allowed_values"
        if not 2 <= len(values) <= 10:
            report.error("INVALID_ALLOWED_VALUES", path, f"{len(values)} options; an enum needs 2 to 10 (use text for more).")
        folded = [v.strip().casefold() for v in values if isinstance(v, str)]
        if len(set(folded)) != len(folded):
            report.error("INVALID_ALLOWED_VALUES", path, "Options repeat, ignoring case.")
        for value in values:
            if not isinstance(value, str) or not value.strip() or len(value) > 64 or value == "<DEFAULT>" or not all(is_letterish(c) for c in value):
                report.error("INVALID_ALLOWED_VALUES", path, f"Invalid option {value!r}: 1-64 characters of letters, digits, space, _ or -.")
            elif NUMBER.match(value) or value.lower() in ("true", "false"):
                report.warn("ENUM_VALUE_LOOKS_LITERAL", path, f"Option {value!r} looks like a number or boolean; the editor writes it unquoted in conditions.")


def check_templates(text, path, variables, report, spoken=False):
    for match in TEMPLATE.finditer(text):
        inner = match.group(1)
        if inner is None or not re.fullmatch(r"[^\W\d]\w*", inner):
            report.error("TEMPLATE_NOT_ALLOWED", path, f"Only plain {{{{name}}}} is allowed, not {match.group(0)!r}.")
        elif inner not in variables:
            report.error("VARIABLE_MISSING", path, f"{{{{{inner}}}}} is not a declared variable.")


def tokenize(when):
    tokens, i = [], 0
    while i < len(when):
        if when[i].isspace():
            i += 1
        elif when[i] == "'":
            j, value = i + 1, ""
            while True:
                if j >= len(when):
                    raise ValueError("unclosed quote")
                if when[j] == "'" and when[j + 1:j + 2] == "'":
                    value, j = value + "'", j + 2
                elif when[j] == "'":
                    break
                else:
                    value, j = value + when[j], j + 1
            tokens.append(("str", value))
            i = j + 1
        elif when[i] == "(":
            j = when.find(")", i)
            if j < 0:
                raise ValueError("unclosed list")
            inner = when[i + 1:j]
            items = [part.strip() for part in re.findall(r"'(?:[^']|'')*'|[^,]+", inner) if part.strip() and part.strip() != ","]
            if not items or not all(item.startswith("'") and item.endswith("'") for item in items):
                raise ValueError("a list holds quoted strings only")
            tokens.append(("list", [item[1:-1].replace("''", "'") for item in items]))
            i = j + 1
        else:
            j = i
            while j < len(when) and not when[j].isspace():
                j += 1
            tokens.append(("word", when[i:j]))
            i = j
    return tokens


def parse_when(when):
    tokens, conditions, joiners, i = tokenize(when), [], set(), 0
    while True:
        if i + 1 >= len(tokens) or tokens[i][0] != "word" or tokens[i + 1][0] != "word":
            raise ValueError("expected: name OPERATOR [value]")
        name, operator = tokens[i][1], tokens[i + 1][1]
        if operator not in OPERATORS:
            raise ValueError(f"unknown operator {operator!r}")
        i += 2
        value = None
        if operator not in ("EXISTS", "NOT_EXISTS"):
            if i >= len(tokens) or (tokens[i][0] == "word" and tokens[i][1] in ("AND", "OR")):
                raise ValueError(f"{operator} needs a value")
            value = tokens[i]
            i += 1
        conditions.append((name, operator, value))
        if i == len(tokens):
            break
        if tokens[i] not in (("word", "AND"), ("word", "OR")):
            raise ValueError(f"unexpected {tokens[i][1]!r}")
        joiners.add(tokens[i][1])
        i += 1
    return conditions, joiners


def check_when(when, path, variables, report, asked):
    try:
        conditions, joiners = parse_when(when)
    except ValueError as problem:
        report.error("WHEN_SYNTAX", path, f"{when!r}: {problem}.")
        return
    if len(joiners) > 1:
        report.error("WHEN_MIXED_JOINERS", path, f"{when!r} mixes AND and OR.")
    if len(conditions) > 10:
        report.error("TOO_MANY_CONDITIONS", path, f"{len(conditions)} conditions; the limit is 10.")
    for name, operator, value in conditions:
        var = variables.get(name)
        if var is None:
            report.error("VARIABLE_MISSING", path, f"'{name}' in a when is not declared.")
            continue
        asked.add(name)
        kind = var.get("type", "text") if var.get("source") == "extracted" else "text"
        if operator not in ALLOWED_OPS[kind]:
            report.error("CONDITION_TYPE_MISMATCH", path, f"{operator} is not allowed for {kind} variable '{name}'.")
            continue
        if value is None:
            continue
        tag, raw = value
        bad = None
        if operator in ("IN", "NOT_IN"):
            if tag != "list":
                bad = "IN/NOT_IN take a list like ('A', 'B')"
            elif any(item.strip().casefold() not in {v.strip().casefold() for v in var.get("allowed_values") or []} for item in raw):
                bad = "every value must be one of allowed_values"
        elif kind in ("text", "enum"):
            if tag != "str":
                bad = "the value must be a quoted string"
            elif kind == "enum" and raw.strip().casefold() not in {v.strip().casefold() for v in var.get("allowed_values") or []}:
                bad = f"{raw!r} is not one of allowed_values"
        elif kind == "boolean":
            if tag != "word" or raw not in ("true", "false"):
                bad = "the value must be true or false, unquoted"
        elif tag != "word" or not NUMBER.match(raw):
            bad = "the value must be an unquoted number"
        elif kind == "number" and operator in ("EQUALS", "NOT_EQUALS") and "." in raw:
            bad = "EQUALS on a number needs a whole number"
        if bad:
            report.error("CONDITION_TYPE_MISMATCH", path, f"'{name}' ({kind}): {bad}.")


def element_path(parent_path, element, siblings):
    index = sum(1 for sibling in siblings[:siblings.index(element) + 1] if sibling.tag == element.tag)
    return f"{parent_path}/{element.tag}[{index}]"


def check_lines(container, path, languages, report):
    texts = [child for child in container if child.tag == "text"]
    if not texts:
        report.error("MISPLACED_ELEMENT", path, f"<{container.tag}> needs at least one <text>.")
    seen = []
    for text in texts:
        lang = text.get("lang", "")
        if lang in seen:
            report.error("DUPLICATE_LANGUAGE", path, f"Two <text> for {lang}.")
        seen.append(lang)
        if languages and lang not in languages:
            report.warn("LANGUAGE_NOT_CONFIGURED", path, f"{lang} is not a bot language (the editor rejects it).")
        children = list(text)
        loose = (text.text or "").strip() or any((child.tail or "").strip() for child in children)
        if children:
            tags = sorted(child.tag for child in children)
            if tags != ["female", "male"] or loose:
                report.error("VOICE_PAIR_INCOMPLETE", path, "A <text> holds a line, or exactly one <male> and one <female>.")
            for child in children:
                line = "".join(child.itertext()).strip()
                if not line:
                    report.error("EMPTY_LINE", path, f"Empty <{child.tag}>.")
                if "{{" in line:
                    report.error("VARIABLE_IN_SPOKEN_LINE", path, "Variables can't be used in spoken lines.")
        else:
            line = (text.text or "").strip()
            if not line:
                report.error("EMPTY_LINE", path, f"Empty <text lang=\"{lang}\">.")
            if "{{" in line:
                report.error("VARIABLE_IN_SPOKEN_LINE", path, "Variables can't be used in spoken lines.")
    if languages and languages[0] not in seen:
        report.error("PRIMARY_LANGUAGE_MISSING", path, f"No line in the primary language {languages[0]}.")
    if languages and texts and seen[0] != languages[0]:
        report.warn("PRIMARY_NOT_FIRST", path, "Put the primary language first; the editor keeps only the first <text> of a transition filler.")


def parse_fragment(source, wrapper, path, report):
    if "<!DOCTYPE" in source:
        report.error("XML_MALFORMED", path, "A DOCTYPE is not allowed.")
        return None
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    try:
        parser.feed(f"<{wrapper}>{source}</{wrapper}>")
        return parser.close()
    except ET.ParseError as problem:
        report.error("XML_MALFORMED", path, f"Not well-formed XML: {problem} (escape & as &amp; and < as &lt;, or reword).")
        return None


def walk_body(element, path, ctx, depth, branch):
    children = list(element)
    previous = None
    for child in children:
        if not isinstance(child.tag, str):
            ctx["report"].error("COMMENT_NOT_ALLOWED", path, "Comments and processing instructions are not allowed.")
            previous = None
            continue
        child_path = element_path(path, child, [c for c in children if isinstance(c.tag, str)])
        tag = child.tag
        if tag not in TAGS:
            ctx["report"].error("UNKNOWN_ELEMENT", child_path, f"<{tag}> is not a supported tag.")
            previous = child
            continue
        required, optional = ATTRS[tag]
        for attr in set(child.attrib) - required - optional:
            ctx["report"].error("UNKNOWN_ATTRIBUTE", child_path, f"<{tag}> has no attribute '{attr}'.")
        for attr in required:
            if not child.get(attr, "").strip():
                ctx["report"].error("MISSING_ATTRIBUTE", child_path, f"<{tag}> needs '{attr}'.")
        if tag not in BODY_TAGS:
            ctx["report"].error("MISPLACED_ELEMENT", child_path, f"<{tag}> can't be used here.")
        elif tag in ("elif", "else") and (previous is None or previous.tag not in ("if", "elif") or (previous.tail or "").strip()):
            ctx["report"].error("MISPLACED_ELEMENT", child_path, f"<{tag}> must come directly after </if> or </elif>.")
        else:
            handle(child, child_path, ctx, depth, branch, element)
        previous = child


def handle(child, path, ctx, depth, branch, parent):
    report, variables, scenario = ctx["report"], ctx["variables"], ctx["scenario"]
    tag = child.tag
    if tag in ("update", "tool"):
        if len(child) or (child.text or "").strip():
            report.error("MISPLACED_ELEMENT", path, f"<{tag}> must be empty.")
        if tag == "update":
            name = child.get("var", "")
            var = variables.get(name)
            if name and var is None:
                report.error("VARIABLE_MISSING", path, f"<update> names undeclared variable '{name}'.")
            elif var is not None:
                ctx["asked"].add(name)
                if var.get("source") == "system":
                    report.error("SYSTEM_VARIABLE_UPDATE", path, f"'{name}' is a system variable and can't be updated.")
                if not (var.get("description") or "").strip():
                    report.warn("UPDATE_WITHOUT_DESCRIPTION", path, f"'{name}' has no description.")
        elif ctx["tools"] is not None and child.get("name") not in ctx["tools"]:
            report.error("TOOL_MISSING", path, f"Tool '{child.get('name')}' is not one of the bot's actions.")
    elif tag == "say":
        if (child.text or "").strip() or any((c.tail or "").strip() for c in child) or any(c.tag != "text" for c in child):
            report.error("MISPLACED_ELEMENT", path, "<say> may contain only <text> elements.")
        check_lines(child, path, ctx["languages"], report)
    elif tag == "transition":
        kind, mode, go_to, when = child.get("type"), child.get("mode"), child.get("go_to"), child.get("when")
        if kind not in (None, "inline", "variable") or mode not in (None, "llm", "auto"):
            report.error("INVALID_ATTRIBUTE_VALUE", path, "type is inline or variable; mode is llm or auto.")
        if go_to and go_to not in ctx["scenarios"]:
            report.error("SCENARIO_MISSING", path, f"go_to '{go_to}' is not a scenario.")
        if go_to == scenario:
            report.error("SELF_TRANSITION", path, "A transition can't go to its own scenario.")
        if go_to:
            ctx["incoming"].add(go_to)
        if mode == "llm" and when is not None:
            report.error("LLM_TRANSITION_WITH_WHEN", path, "An llm transition can't have a when.")
        if kind == "inline" and when is not None:
            report.error("TRANSITION_TYPE_MISMATCH", path, "An inline transition has no when; use type=\"variable\".")
        if mode == "auto" and when is None and branch is None:
            report.error("AUTO_TRANSITION_UNCONDITIONAL", path, "An auto transition needs a when, or must be alone in an If branch.")
        if kind == "variable" and mode == "llm":
            report.error("TRANSITION_MODE_MISMATCH", path, "A variable transition is always auto.")
        if kind == "inline" and branch is not None:
            others = [c for c in branch if c is not child]
            alone = not others and not (branch.text or "").strip() and not (child.tail or "").strip()
            if mode == "auto" and not alone:
                report.error("TRANSITION_MODE_MISMATCH", path, "An inline transition next to other content in a branch must be llm.")
            if mode == "llm" and alone:
                report.error("TRANSITION_MODE_MISMATCH", path, "An inline transition alone in a branch must be auto.")
        fillers = [c for c in child if c.tag == "filler"]
        if len(fillers) > 1 or any(c.tag != "filler" for c in child) or (child.text or "").strip():
            report.error("MISPLACED_ELEMENT", path, "A transition holds at most one <filler> and nothing else.")
        for filler in fillers:
            check_lines(filler, path + "/filler[1]", ctx["languages"], report)
        if when is not None:
            check_when(when, path, variables, report, ctx["asked"])
    elif tag in ("if", "elif", "else"):
        if tag != "else":
            check_when(child.get("when", ""), path, variables, report, ctx["asked"])
        if depth + 1 > 3:
            report.error("IF_NESTING", path, "If blocks are nested more than 3 levels.")
        if not len(child) and not (child.text or "").strip():
            report.error("EMPTY_BRANCH", path, "Empty branch (the editor blocks it; the validator warns).")
        walk_body(child, path, ctx, depth + 1, child)


def check(config, languages, tools):
    report = Report()
    check_schema(config, report)
    if report.errors:
        return report
    variables, scenarios = config.get("variables_schema", {}), config["scenarios"]
    if config["start"] not in scenarios:
        report.error("SCENARIO_MISSING", "start", f"start '{config['start']}' is not a scenario.")
    check_variables(variables, report)
    for key, value in config["global_prompt"].items():
        if MARKUP.search(value):
            report.error("MARKUP_IN_GLOBAL_PROMPT", f"global_prompt.{key}", "Scenario tags are not allowed in the global prompt.")
        check_templates(value, f"global_prompt.{key}", variables, report)
    ctx = {"report": report, "variables": variables, "scenarios": scenarios, "languages": languages, "tools": tools,
           "asked": set(), "incoming": set()}
    targets = {}
    for name, item in config.get("global_transitions", {}).items():
        path = f"global_transitions.{name}"
        if MARKUP.search(item["when_llm"]):
            report.error("MARKUP_IN_GLOBAL_PROMPT", f"{path}.when_llm", "Tags are not allowed in when_llm.")
        check_templates(item["when_llm"], f"{path}.when_llm", variables, report)
        if item["go_to"] not in scenarios:
            report.error("SCENARIO_MISSING", f"{path}.go_to", f"go_to '{item['go_to']}' is not a scenario.")
        ctx["incoming"].add(item["go_to"])
        if item["go_to"] in targets:
            report.error("DUPLICATE_GLOBAL_TARGET", f"{path}.go_to", f"'{item['go_to']}' is already the target of '{targets[item['go_to']]}' (the editor allows one).")
        targets[item["go_to"]] = name
        if "filler" in item:
            root = parse_fragment(item["filler"], "filler", f"{path}.filler", report)
            if root is not None:
                if (root.text or "").strip() or any(c.tag != "text" for c in root):
                    report.error("MISPLACED_ELEMENT", f"{path}.filler", "A global filler holds only <text> lines.")
                check_lines(root, f"{path}.filler", languages, report)
    for name, source in scenarios.items():
        path = f"scenarios.{name}"
        ctx["scenario"] = name
        check_templates(source, path, variables, report)
        if len(source) > NEAR:
            report.warn("NEAR_SIZE_LIMIT", path, f"{len(source)} of {MAX_SCENARIO} characters.")
        root = parse_fragment(source, "scenario", path, report)
        if root is not None:
            walk_body(root, path, ctx, 0, None)
    for name in scenarios:
        if name != config["start"] and name not in ctx["incoming"]:
            report.warn("UNREACHABLE_SCENARIO", f"scenarios.{name}", "No transition or interrupt leads here.")
    for name, var in variables.items():
        if var.get("source") == "extracted" and name not in ctx["asked"]:
            report.warn("VARIABLE_NEVER_ASKED", f"variables_schema.{name}", "Never in an <update> or a when, so never captured.")
    if tools is None:
        report.warn("TOOLS_NOT_CHECKED", "(root)", "Pass --tools to check <tool name> against the bot's actions.")
    if not languages:
        report.warn("LANGUAGES_NOT_CHECKED", "(root)", "Pass --languages (primary first) to check spoken lines.")
    return report


def main():
    parser = argparse.ArgumentParser(description="Check a scenario_config version 2 offline.")
    parser.add_argument("path")
    parser.add_argument("--languages", default="")
    parser.add_argument("--tools", default=None)
    args = parser.parse_args()
    languages = [x.strip() for x in args.languages.split(",") if x.strip()]
    tools = None if args.tools is None else {x.strip() for x in args.tools.split(",") if x.strip()}
    report = check(load(args.path), languages, tools)
    for code, path, message in report.errors:
        print(f"ERROR   {code:28s} {path}: {message}")
    for code, path, message in report.warnings:
        print(f"warning {code:28s} {path}: {message}")
    print(f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
