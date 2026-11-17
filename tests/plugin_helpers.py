"""Small tools the structural tests of the plugin share."""
import argparse
import hashlib
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


# The real names of the author's own runs (the companies, their competitors and investors, the screened startup, the
# fund, the places), which the project must not publish. The file holds only SHA-256 digests of the names: lower
# case, one space between the words, one digest per spelling (with and without the gap, ae/oe or a/o). A name of
# several words is also found with a hyphen or any whitespace between its words.
_NAME_DIGESTS = frozenset({
    "080f487fb62a439e14d014a808414249797d8a262e28301f2608fa178b610b93",
    "0e13862ad5ee78f21491a9c37a6804fcdb20ba534f47102cffb891b74d0e2050",
    "112da95eeb1d7470a584abae78eb5b65518b3f0b25a57fb35242eaa522854d45",
    "13f8a313716d8ea760a3f3ccd880e150173f820201637900a32badd21e3d3544",
    "1cf47146983547beef8d80c62e11152e1cfe46d8a1f2e30b64776ead94e5df87",
    "332a35baaefc44113f815a691b78b5a28d94bb4074ff817e330138c3bd4cf5e2",
    "3740b2b6a592f7c1931b80ecee61e5485c838bb7858c28743bd1c096045640dc",
    "49f6a54a7a3243057a8e3d987ca42c303c9cbdbb06100188ddc8c1988699da46",
    "4a1b3c6bb396fdf36b23516e3872280d12fc383be7af7e7ade22d23a164ca589",
    "4e7168d510d68a578775403309fe0c98277ed9b230266e8d0786e391c3caa8c8",
    "5882601e7f20c2faf6dd86054c185a5b1a10050de5112be72fa373a566f3b3fb",
    "590c8208b6ef0cc1b2668ec514b10a253953a015b9ec3c67b215fbdba0317ee7",
    "5d07878b41ae0005521275c2bb559b14b4336ad7e3a1432e48261ec2fbbcf30e",
    "5d52fe975517f42d4a240d817fc1771cdc248b5dde4a1ee58df80cda1752c482",
    "78f8712832addf0fd632897f3215006bf2cd22f4af5f1ee45bd3018f8cdd014e",
    "7b767aad874061deadccbd889cfde096de7f55cf172a8b4638871be0038b9805",
    "a4cbfc0fbd00fdfa4d6eea3cf733eb38a4048a931c7975832ed07b911bb64133",
    "afd14f44fbfa1d70b43b6106bcf3e66ad48257321f4cab86d369b48f21076b0b",
    "b19ca7c8e2f1594f7a240a659367888c2c2335fdf97d8f67a29dbb59ffb6d4ad",
    "b63d766686c3c83138dd699193bd0c2bb9c1c523b788d5b45382ac1e0c50070a",
    "bd1238ef102d72e777d10377ed5a554827e5a002fcedc670fd16e452bad9f411",
    "c2adb3baeaa4526021aa08fb535fe305ac7970bd352bf495a68dea2d8619ee58",
    "da93ca4e9b9e3ed075b4e286958470154df4d3ec758dc9228856b01dcffd8bfc",
    "e20ceb7077c81ab854a67831f65167ab38c5609c8e5655c85ec272b49c27566a",
    "e3b111c07d4f04f041de8cd3836190ddb6605fb136deb823712eafa98ea7355e",
    "eb18bae81c6b2128d9963fe0dae6f76650506be7af13cb90549107222e0c8285",
    "f78e7ef693c8ab8e5a095c88f8c2b655c8779afb8ca70beef2462c8e23579596",
    "fd41a9179efcfe8f0f6a9773fbfab5044cc2c5418f96e1778d570c4798142aff",
})
_MAX_NAME_WORDS = 2  # the most words in one name
_WORD = re.compile(r"[^\W_]+")
_JOINT = re.compile(r"\s+|-")  # what may stand between the words of one name


def _digest(words: list[str]) -> str:
    return hashlib.sha256(" ".join(words).lower().encode("utf-8")).hexdigest()


def company_names_in(text: str) -> list[str]:
    """Every spelling of any of those names in a text, as it is written there (whole words only)."""
    words = list(_WORD.finditer(text))
    found, i = [], 0
    while i < len(words):
        for n in range(min(_MAX_NAME_WORDS, len(words) - i), 0, -1):
            run = words[i:i + n]
            if all(_JOINT.fullmatch(text[a.end():b.start()]) for a, b in zip(run, run[1:])) \
                    and _digest([w.group() for w in run]) in _NAME_DIGESTS:
                found.append(text[run[0].start():run[-1].end()])
                i += n - 1
                break
        i += 1
    return found


# Every folder the public copy ships besides the plugin's own (docs/superpowers and .claude stay private)
SHIPPED_FOLDERS = PLUGIN_FOLDERS + ("tests", "engine", "lenses", "docs", "evals", "bin", "scripts", ".claude-plugin")


def shipped_text_files() -> list[Path]:
    """The text files of the public copy that exist now: README and every shipped folder, without docs/superpowers
    and without what git ignores there (evals/results, caches)."""
    files = [ROOT / "README.md"]
    for folder in SHIPPED_FOLDERS:
        base = ROOT / folder
        if base.is_dir():
            files.extend(p for p in sorted(base.rglob("*")) if p.is_file() and p.suffix in TEXT_SUFFIXES
                         and not {"superpowers", "results", "__pycache__"} & set(p.relative_to(ROOT).parts[:-1]))
    return files


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
