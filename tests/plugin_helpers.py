"""Small tools the structural tests of the plugin share."""
import argparse
import json
import re
import shutil
from pathlib import Path

from radar.cli import build_parser

ROOT = Path(__file__).resolve().parent.parent

PLUGIN_FOLDERS = ("skills", "agents", "references", "hooks", "packs", "settings")
TEXT_SUFFIXES = {".md", ".json", ".py", ".txt", ".sh", ".yaml", ".yml", ".toml", ".html"}

_SPAN = re.compile(r"`([^`\n]+)`")
_OPTION_WORD = re.compile(r"--[A-Za-z][\w-]*(=|$)")


_INDICATORS = {">", "|", ">-", "|-", ">+", "|+"}


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def front_matter(path: Path) -> dict[str, str]:
    """The `key: value` lines between the first two `---` lines, values as text, quotes removed.

    An indented line belongs to the key above it. Plain continuation lines (a folded `description: >`)
    are joined with single spaces. A list under a key (`- item` lines) gives the items joined with ", ".
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    parts: dict[str, list[str]] = {}
    is_list: dict[str, bool] = {}
    key = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t":
            if key is None:
                continue
            text = line.strip()
            if text.startswith("- ") or text == "-":
                is_list[key] = True
                text = text[1:].strip()
            if text:
                parts[key].append(_unquote(text))
            continue
        name, sep, value = line.partition(":")
        if not sep:
            key = None
            continue
        key = name.strip()
        value = value.strip()
        parts[key] = [] if value in _INDICATORS or not value else [_unquote(value)]
        is_list[key] = False
    return {k: (", " if is_list[k] else " ").join(v) for k, v in parts.items()}


def body(path: Path) -> str:
    """Everything after the front matter."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "".join(lines[index + 1:])
    return text


_FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")


def _candidates(text: str) -> list[str]:
    """The pieces of text that count as code: every line of a fenced block and every inline code span."""
    text = re.sub(r"\\\n[ \t]*", " ", text)          # a line ending in a backslash goes on
    found = []
    fence = None
    for line in text.splitlines():
        match = _FENCE.match(line)
        if fence is None:
            if match:
                fence = match.group(1)
            else:
                found.extend(_SPAN.findall(line))
        elif match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence) and not match.group(2).strip():
            fence = None
        else:
            found.append(line)
    return found


def _segments(code: str) -> list[list[tuple[str, bool]]]:
    """Split shell text into command segments of (word, started_with_a_quote); quotes are removed from words."""
    segments, words = [], []
    word, quoted, has_word, i, n = "", False, False, 0, len(code)

    def end_word():
        nonlocal word, quoted, has_word
        if has_word:
            words.append((word, quoted))
        word, quoted, has_word = "", False, False

    def end_segment():
        nonlocal words
        end_word()
        segments.append(words)
        words = []

    while i < n:
        c = code[i]
        if c in "\"'":
            if not has_word:
                quoted = True
            has_word = True
            j = i + 1
            while j < n and code[j] != c:
                if c == '"' and code[j] == "\\" and j + 1 < n:
                    j += 1
                word += code[j]
                j += 1
            word += ""
            i = j + 1
            continue
        if code.startswith("$(", i):
            end_segment()
            i += 2
        elif code.startswith(("&&", "||"), i):
            end_segment()
            i += 2
        elif c in ";|`()\n":
            end_segment()
            i += 1
        elif c in " \t":
            end_word()
            i += 1
        else:
            word += c
            has_word = True
            i += 1
    end_segment()
    return segments


def radar_calls(text: str) -> list[tuple[str, set[str]]]:
    """Every radar call at a command boundary in code: the subcommand and its --options.

    A command boundary is the start of a line or span, a `$ ` prompt, `$(`, a backtick, `&&`, `||`, `;` or `|`.
    The program may be named `radar` or by a path ending in `/bin/radar`, quoted or not. A word inside a quoted
    argument is never an option; `--key=value` counts as `--key`. A call with no subcommand (`radar --help`)
    gives the subcommand "" and the options it has.
    """
    calls = []
    for code in _candidates(text):
        for words in _segments(code):
            while words and (words[0][0] == "$" or re.fullmatch(r"\w+=\S*", words[0][0])):
                words = words[1:]
            if len(words) < 2:
                continue
            program = words[0][0]
            if program != "radar" and not program.endswith("/bin/radar"):
                continue
            rest = words[1:]
            command = ""
            if not (rest[0][0].startswith("--") and not rest[0][1]):
                command, rest = rest[0][0], rest[1:]
            options = {w.split("=", 1)[0] for w, quoted in rest if not quoted and _OPTION_WORD.match(w)}
            calls.append((command, options))
    return calls


def cli_options() -> dict[str, set[str]]:
    """Every subcommand of the engine's parser with its option strings, plus --from-json for all."""
    result = {}
    for action in build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                options = {o for a in sub._actions for o in a.option_strings if o.startswith("--")}
                result[name] = options | {"--from-json"}
    return result


def unknown_calls(text: str) -> list[str]:
    """The calls in `text` whose subcommand or options the engine does not know."""
    known = cli_options()
    unknown = []
    for command, options in radar_calls(text):
        if command == "":
            unknown.extend(f"radar: unknown option {o}" for o in sorted(options - {"--help", "--version"}))
            continue
        if command not in known:
            unknown.append(f"{command}: unknown command")
            continue
        for option in sorted(options - known[command] - {"--help"}):
            unknown.append(f"{command}: unknown option {option}")
    return unknown


def plugin_text_files() -> list[Path]:
    """The plugin's own text files that exist now, so tests grow with the plugin."""
    files = []
    for folder in PLUGIN_FOLDERS:
        base = ROOT / folder
        if base.is_dir():
            files.extend(p for p in sorted(base.rglob("*")) if p.is_file() and p.suffix in TEXT_SUFFIXES)
    return files


def has_claude() -> bool:
    return shutil.which("claude") is not None


def fenced_text(path: Path, tag: str, last: bool = False) -> str:
    """The text of the one fenced block whose opening line ends with `tag` (```json radar-constants, ```text name).

    The file needs exactly one such block and it must be closed. With `last=True` nothing but blank lines
    may follow it. A fence line has exactly three backticks.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines)
              if line.strip().startswith("```") and line.strip()[3:].split()[-1:] == [tag]]
    assert len(starts) == 1, f"the file needs exactly one block tagged {tag}"
    ends = [i for i in range(starts[0] + 1, len(lines)) if lines[i].strip() == "```"]
    assert ends, f"the block tagged {tag} is not closed"
    if last:
        assert not "".join(lines[ends[0] + 1:]).strip(), f"the block tagged {tag} must come last"
    return "\n".join(lines[starts[0] + 1:ends[0]])


def fenced_json(path: Path, tag: str, last: bool = False):
    """The JSON value in the one fenced block tagged `tag`."""
    return json.loads(fenced_text(path, tag, last))


def merge_allow(existing: str | None, line: str) -> tuple[str | None, str]:
    """What the start skill does to `.claude/settings.local.json`, as its words describe it.

    `existing` is the file's text, or None when the file is missing. Returns (text to write, status):
    "created" (no file: a new file holding the line), "added" (the line goes at the end of permissions.allow,
    everything else kept as it is), "already" (the line is there: nothing to write) or "unreadable" (the text is not
    JSON, not an object, or its `permissions` is not an object, or its `allow` is not a list: nothing is written).
    """
    if existing is None:
        return json.dumps({"permissions": {"allow": [line]}}, indent=2) + "\n", "created"
    try:
        settings = json.loads(existing)
    except ValueError:
        return None, "unreadable"
    if not isinstance(settings, dict):
        return None, "unreadable"
    permissions = settings.get("permissions", {})
    if not isinstance(permissions, dict):
        return None, "unreadable"
    allow = permissions.get("allow", [])
    if not isinstance(allow, list):
        return None, "unreadable"
    if line in allow:
        return None, "already"
    settings["permissions"] = {**permissions, "allow": [*allow, line]}
    return json.dumps(settings, indent=2, ensure_ascii=False) + "\n", "added"
