"""The guard: a second safety net of the Strategy Radar plugin. The gate stays the real check.

Claude Code starts this file (through hooks/guard.sh) before a Write, Edit, NotebookEdit or Bash call
and hands it the call as JSON on standard input. Exit code 2 refuses the call, and the reason on
standard error is shown to the model. Exit code 0 lets the call through.

Rule 1, for everyone: inside a run folder only the lead's four places are written by hand
(analysis.json, notes/, proposals/, inbox/). Everything else there belongs to the radar program.
A hand write is refused as well when the guard cannot follow the file name, part by part, to the
place where it lands, and when that place is one that each program sees for itself or that is named by
numbers (SHORTCUT_FOLDERS), see _follow and _judge. A write into a file with another name as well is
refused with its own reason, see _has_other_names.
Rule 2, for the plugin's helpers: only the support checker, the lens advisor, the two link readers, the project
grouper and the claim matcher run commands, each only its own two, in the form its file shows, and a command that
records names the helper itself (see _fits). The other three run none.
Rule 3, for every other caller (the lead, any other agent): a command that holds the word record-support,
record-link-check, record-lens-recommendation, record-projects or record-claim-groups is refused, because only the
support checker records a verdict, only the two link readers record a link verdict, only the lens advisor records the
recommendation, only the project grouper records the projects and only the claim matcher records the claim groups, see
_decide.

An event the guard cannot read (not JSON, not an object, a value of another kind than expected,
no file named) is let through: the guard must never break a session. But a helper is never unlimited:
an error of the guard's own while it judges a helper's call refuses that call (FAILED_REASON), see decide.
This file may run on a Python as old as 3.8: standard library only.
"""
import errno
import json
import os
import re
import stat
import sys
import unicodedata

# Every sentence the guard prints begins with its name: the hook runs in every project, and a person in an unrelated
# project must know who refused.
SENDER = "Strategy Radar's guard: "
RECORDS_REASON = SENDER + "Run records are written only by the radar program. Use the radar command for this step."
HELPER_REASON = SENDER + "This helper may only run: radar quote-context and radar record-support."
NO_COMMANDS_REASON = SENDER + "This helper may not run commands."
VERDICT_REASON = SENDER + ("Only the support checker records whether a quote supports its fact. "
                           "Ask the support checker to check this fact.")
UNCHECKED_REASON = SENDER + "The guard cannot check where this path leads. Use a shorter, plain path."
SECOND_NAME_REASON = SENDER + ("This file also has a second name somewhere else on this computer, and the guard cannot "
                               "see where, so it is not written by hand. Save a fresh copy of the file under a new name "
                               "and work on that.")
FAILED_REASON = SENDER + "The guard could not check this call, so a helper may not make it."
ADVISOR_REASON = SENDER + "This helper may only run: radar lens-advisor-input and radar record-lens-recommendation."
READER_REASON = SENDER + "This helper may only run: radar lens-link-context and radar record-link-check."
LINK_VERDICT_REASON = SENDER + ("Only the two link readers record whether a fact bears on a lens. "
                                "Ask the link readers to read the suggested links.")
LIST_REASON = SENDER + ("Only the lens advisor records the lens recommendation. "
                        "Ask the lens advisor to make the list.")
GROUPER_REASON = SENDER + "This helper may only run: radar project-grouper-input and radar record-projects."
PROJECTS_REASON = SENDER + ("Only the project grouper records the projects. "
                            "Ask the project grouper to group the moves.")

MATCHER_REASON = SENDER + "This helper may only run: radar claim-matcher-input and radar record-claim-groups."
CLAIMS_REASON = SENDER + ("Only the claim matcher records the claim groups. "
                          "Ask the claim matcher to match the proposals.")

PLUGIN = "strategy-radar"
HELPERS = ("source-scout", "fact-extractor", "support-checker", "bias-auditor",
           "lens-advisor", "lens-link-reader", "lens-link-reader-quick", "project-grouper", "claim-matcher")
CHECKER = "support-checker"

WRITING_TOOLS = ("Write", "Edit", "NotebookEdit")
PATH_KEYS = ("file_path", "notebook_path")           # NotebookEdit names its file notebook_path
LEAD_FILE = b"analysis.json"                         # at the root of the run folder
LEAD_FOLDERS = (b"notes", b"proposals", b"inbox")
LONGEST_PATH = 4096       # bytes. Only a quick first check: a longer text is refused without a look at the
#                           disk. Linux opens at most 4095 bytes and macOS 1023; the guard relies on neither
#                           number, it asks the computer about every part of a path, see _follow.
MOST_LINKS = 40           # links followed for one path. Linux follows 40 at most and macOS 32; a path with more
#                           links than the computer follows is one it does not open, so judging it does no harm
SHORTCUT_FOLDERS = ("/proc", "/dev/fd", "/.vol")
# Below these folders a name does not lead to the same place for every program: in /proc and /dev/fd each program
# finds its own folder and its own open files, and the guard is not the program that writes; in /.vol macOS opens
# a file by the numbers of its disk and its entry, so the folders on the way are never named. A place in one of them
# cannot be checked. They are known by what the computer says they are, not by how a path spells them.

HEREDOC_OPENER = "<<'RADAR_NOTE'"                    # the end mark in single quotes: the shell changes nothing inside
HEREDOC_END = "RADAR_NOTE"
CHECKER_BY = "support-checker"                       # the one name the checker records its verdicts under
VERDICT_WORD = "record-support"                      # the command that records a verdict
OPTIONS = {                                          # each one exactly once, in any order
    "quote-context": ("--run", "--fact"),
    "record-support": ("--run", "--fact", "--passed", "--by", "--note-stdin"),
}
SWITCHES = ("--note-stdin", "--list-stdin")         # options that take no value
OPTIONAL = {                                         # options a subcommand may also take, at most once
    "lens-advisor-input": ("--part",),               # the input comes in parts; the helper reads them one by one
    "project-grouper-input": ("--part",),
    "claim-matcher-input": ("--part",),
    "lens-link-context": ("--part",),
}
_PART = re.compile(r"[1-9][0-9]*")                   # a part is a positive whole number, written plainly
CHECKER_COMMANDS = {                                 # each subcommand: its options and the here-document it takes
    "quote-context": (OPTIONS["quote-context"], None),
    "record-support": (OPTIONS["record-support"], (HEREDOC_OPENER, HEREDOC_END)),
}
LIST_OPENER = "<<'RADAR_LIST'"                       # the advisor's list comes as plain lines in its own here-document
LIST_END = "RADAR_LIST"
LINK_VERDICT_WORD = "record-link-check"              # the command that records a link verdict
LIST_WORD = "record-lens-recommendation"             # the command that records the recommendation
PROJECTS_WORD = "record-projects"                    # the command that records the projects
CLAIMS_WORD = "record-claim-groups"                  # the command that records the claim groups
_READER_COMMANDS = {
    "lens-link-context": (("--run", "--lenses"), None),
    "record-link-check": (("--run", "--lens", "--fact", "--verdict", "--by", "--note-stdin"),
                          (HEREDOC_OPENER, HEREDOC_END)),
}
LENS_COMMANDS = {                                    # what each lens helper may run; its --by is its own name
    "lens-advisor": {
        "lens-advisor-input": (("--run", "--lenses"), None),
        "record-lens-recommendation": (("--run", "--lenses", "--by", "--list-stdin"), (LIST_OPENER, LIST_END)),
    },
    "lens-link-reader": _READER_COMMANDS,
    "lens-link-reader-quick": _READER_COMMANDS,
}
LENS_REASONS = {"lens-advisor": ADVISOR_REASON, "lens-link-reader": READER_REASON,
                "lens-link-reader-quick": READER_REASON}
GROUPER_COMMANDS = {                                 # the project grouper's own table; its --by is its own name
    "project-grouper": {
        "project-grouper-input": (("--run",), None),
        "record-projects": (("--run", "--by", "--list-stdin"), (LIST_OPENER, LIST_END)),
    },
}
MATCHER_COMMANDS = {                                 # the claim matcher's own table; its --by is its own name
    "claim-matcher": {
        "claim-matcher-input": (("--run", "--sources"), None),
        "record-claim-groups": (("--run", "--sources", "--by", "--list-stdin"), (LIST_OPENER, LIST_END)),
    },
}
RECORD_WORDS = ((VERDICT_WORD, VERDICT_REASON), (LINK_VERDICT_WORD, LINK_VERDICT_REASON), (LIST_WORD, LIST_REASON),
                (PROJECTS_WORD, PROJECTS_REASON), (CLAIMS_WORD, CLAIMS_REASON))
_BARE_WORD = re.compile(r"[A-Za-z0-9._/:-][A-Za-z0-9._/:=-]*")
_FACT_ID = re.compile(r"F[0-9]+")
_SOURCE_IDS = re.compile(r"S[0-9]+(,S[0-9]+)*")      # S1,S2: plain, no spaces
_LENS_ID = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]*")  # a lens name, plain letters only; never an option
_UNSEEN = ("Cc", "Cf", "Cs", "Zs", "Zl", "Zp")       # control, format, half a pair, spaces, line breaks


def _own_radar():
    """This plugin's own program: bin/radar next to the folder this file really lies in."""
    try:
        hooks = os.path.dirname(os.path.realpath(os.path.abspath(__file__)))
        return os.path.realpath(os.path.join(os.path.dirname(hooks), "bin", "radar")).encode("utf-8", "surrogatepass")
    except Exception:
        return None


OWN_RADAR = _own_radar()


def _shortcuts():
    """The folders of SHORTCUT_FOLDERS that this computer has, as (disk, entry) numbers."""
    found = set()
    for folder in SHORTCUT_FOLDERS:
        try:
            info = os.lstat(folder)
        except Exception:
            continue
        if stat.S_ISDIR(info.st_mode):
            found.add((info.st_dev, info.st_ino))
    return found


SHORTCUTS = _shortcuts()


# ---------------------------------------------------------------- rule 1: run records

def _as_bytes(text):
    """Paths are handled as bytes: any text can be turned into them, whatever the computer's language setting."""
    return text.encode("utf-8", "surrogatepass")


def _is_run_folder(folder):
    """A run folder holds run.json and both folders of records, sources/ and facts/."""
    try:
        if not os.path.lexists(os.path.join(folder, b"run.json")):
            return False
        return os.path.isdir(os.path.join(folder, b"sources")) and os.path.isdir(os.path.join(folder, b"facts"))
    except (ValueError, OSError):
        return False                                 # a name no computer can hold names no folder


def _is_the_lead_s(parts):
    """`parts` is a path below a run folder. True for analysis.json at its root and anything under the three folders."""
    return parts == [LEAD_FILE] or (len(parts) > 1 and parts[0] in LEAD_FOLDERS)


def _is_refused(path):
    """True when `path` lies in a run folder, seen from any folder above it, outside the lead's four places.

    `path` starts with a slash and holds no `.` or `..`.
    """
    parts = [part for part in path.split(b"/") if part]
    if parts and _is_run_folder(b"/") and not _is_the_lead_s(parts):
        return True
    folder = b""
    for index in range(len(parts) - 1):
        folder += b"/" + parts[index]
        if _is_run_folder(folder) and not _is_the_lead_s(parts[index + 1:]):
            return True
    return False


def _follow(text):
    """The place where `text` (a path from the top folder, as bytes) lands, or None when that cannot be checked.

    The path is followed one part at a time, the way a computer does, and nothing is assumed:
    - an empty part and `.` are skipped; `..` steps back from the place reached so far;
    - for any other part the computer is asked (os.lstat) what it is at the place reached so far;
    - a link is read and followed: its own parts come before the parts still to go, and a link that
      starts with a slash starts again at the top; more than MOST_LINKS links cannot be checked;
    - a folder is stepped into, unless it is one of the SHORTCUTS: a place there cannot be checked;
    - a file, or a part that is not there: the parts still to go are added as they are written, as new
      names below it. If one of them is `..` the place cannot be checked: no computer opens such a path,
      and where it would lead is not guessed;
    - any other answer of the computer (path or name too long, no permission, anything else), and a
      link that cannot be read, cannot be checked.
    """
    place = []                 # the parts of the place reached so far
    paths = [b""]              # paths[n] is the path of the first n parts
    to_go = text.split(b"/")
    to_go.reverse()
    links = 0
    while to_go:
        part = to_go.pop()
        if part in (b"", b"."):
            continue
        if part == b"..":
            if place:
                place.pop()
                paths.pop()
            continue
        here = paths[-1] + b"/" + part
        try:
            found = os.lstat(here)
            kind = found.st_mode
        except OSError as error:
            if error.errno not in (errno.ENOENT, errno.ENOTDIR):
                return None
            kind = None
        except Exception:
            return None
        if kind is not None and stat.S_ISDIR(kind) and (found.st_dev, found.st_ino) in SHORTCUTS:
            return None
        if kind is not None and stat.S_ISLNK(kind):
            links += 1
            if links > MOST_LINKS:
                return None
            try:
                target = os.readlink(here)
            except Exception:
                return None
            if not isinstance(target, bytes) or not target:
                return None
            if target.startswith(b"/"):
                place, paths = [], [b""]
            to_go.extend(reversed(target.split(b"/")))
            continue
        place.append(part)
        paths.append(here)
        if kind is None or not stat.S_ISDIR(kind):
            rest = [name for name in reversed(to_go) if name not in (b"", b".")]
            if b".." in rest:
                return None
            place.extend(rest)
            break
    return b"/" + b"/".join(place)


def _has_other_names(place):
    """True when a write to `place` (a path _follow worked out) lands in a file with more than one name, a hard
    link: the guard cannot see where the other names are, and a write by this one changes the file under all of
    them. The file asked about is the deepest part of the place that is there, because a place below a file lands
    in that file too (on macOS file/..namedfork/rsrc is a second stream of the file). _follow has already asked
    about every part that is there, so a question that fails here finds no such file."""
    path = b""
    for part in place.split(b"/"):
        if not part:
            continue
        path += b"/" + part
        try:
            found = os.lstat(path)
        except Exception:
            return False
        if not stat.S_ISDIR(found.st_mode):
            return stat.S_ISREG(found.st_mode) and found.st_nlink > 1
    return False


def _judge(file_path, cwd):
    """The reason for refusing a hand write to `file_path`, or None.

    The name is joined with the folder the event names (the hook's own folder, or the top folder, when the
    event names none). It cannot be checked, and is refused, when the name or the folder holds the character
    that ends a name (NUL) or the joined text is longer than LONGEST_PATH bytes. Otherwise three places are
    worked out:
    1. the tidied text: `.`, `..` and doubled slashes struck out, links not followed. The radar program
       reads a run by such names, so a records folder that is itself a link stays protected;
    2. where the tidied text lands when followed with _follow: a tool that tidies the path first writes there;
    3. where the text as written lands when followed with _follow: a tool that hands the text to the
       computer as it is writes there.
    A place in a run folder outside the lead's four places refuses the call as a run record. If none does,
    but place 2 or 3 cannot be checked, the call is refused as one that cannot be checked; if they can, but one
    lands in a file with another name as well (_has_other_names), it is refused for that, in its own words,
    because no other spelling of the path would help.
    A name that starts with `~` is judged a second time from the home folder, in the same way.
    """
    name = _as_bytes(file_path)
    if isinstance(cwd, str) and cwd:
        base = _as_bytes(cwd)
    else:
        try:
            base = os.getcwdb()
        except Exception:
            base = b"/"
    written = [os.path.join(b"/", base, name)]
    if name.startswith(b"~"):
        try:
            written.append(os.path.join(b"/", base, os.path.expanduser(name)))
        except Exception:
            pass
    if b"\0" in base or any(b"\0" in path or len(path) > LONGEST_PATH for path in written):
        return UNCHECKED_REASON
    unchecked = second_name = False
    for path in written:
        tidied = os.path.normpath(path)
        if _is_refused(tidied):
            return RECORDS_REASON
        for text in (tidied, path):
            place = _follow(text)
            if place is None:
                unchecked = True
            elif _is_refused(place):
                return RECORDS_REASON
            elif _has_other_names(place):
                second_name = True
    if unchecked:
        return UNCHECKED_REASON
    return SECOND_NAME_REASON if second_name else None


def _judge_write(event):
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    reasons = []
    for key in PATH_KEYS:
        file_path = tool_input.get(key)
        if isinstance(file_path, str) and file_path:
            reasons.append(_judge(file_path, event.get("cwd")))
    for reason in (RECORDS_REASON, UNCHECKED_REASON, SECOND_NAME_REASON):
        if reason in reasons:
            return reason
    return None


# ---------------------------------------------------------------- rule 2: what a helper may run

def _helper_name(agent_type):
    """The helper's plain name when the call comes from one of this plugin's helpers, else None."""
    if not isinstance(agent_type, str):
        return None
    if agent_type in HELPERS:
        return agent_type
    plugin, colon, name = agent_type.partition(":")
    if colon and plugin == PLUGIN and name in HELPERS:
        return name
    return None


def _inert(text):
    """True when double-quoted `text` is not empty, holds none of the four marks a shell reads inside
    double quotes, and holds no control, format or line-break character, half of a pair, or space
    other than the plain one."""
    for char in text:
        if char in '"$`\\' or (char != " " and unicodedata.category(char) in _UNSEEN):
            return False
    return bool(text)


def _is_own_radar(program):
    """True when `program` is this plugin's own bin/radar, named so that the launcher finds its own engine.

    The launcher looks for the engine next to the name it is started by. So the path is taken as written:
    no `.` or `..` in it, the file itself is no link, the file is this plugin's bin/radar,
    and the folder two levels up is this plugin's folder.
    """
    try:
        path = _as_bytes(program)
        parts = path.split(b"/")
        if OWN_RADAR is None or parts[0] != b"" or parts[-2:] != [b"bin", b"radar"]:
            return False
        if any(part in (b"", b".", b"..") for part in parts[1:]) or os.path.islink(path):
            return False
        plugin = os.path.dirname(os.path.dirname(path))
        return _follow(path) == OWN_RADAR and _follow(plugin) == os.path.dirname(os.path.dirname(OWN_RADAR))
    except Exception:
        return False


def _words(line, openers):
    """Split one line at spaces into (text, was_quoted) words; None when it holds a quoting the guard does not allow.
    The here-document openers in `openers` are the only words with a single quote that stand outside double quotes."""
    words = []
    position, end = 0, len(line)
    while position < end:
        if line[position] == " ":
            position += 1
        elif line[position] == '"':
            close = line.find('"', position + 1)
            if close < 0 or (close + 1 < end and line[close + 1] != " "):
                return None
            text = line[position + 1:close]
            if not _inert(text):
                return None
            words.append((text, True))
            position = close + 1
        else:
            stop = line.find(" ", position)
            stop = end if stop < 0 else stop
            word = line[position:stop]
            if word not in openers and not _BARE_WORD.fullmatch(word) and not _SOURCE_IDS.fullmatch(word):
                return None
            words.append((word, False))
            position = stop
    return words


def _value_fits(option, text, quoted, by):
    if option in ("--run", "--lenses"):
        return not text.startswith("-")
    if quoted:
        return False
    if option == "--fact":
        return _FACT_ID.fullmatch(text) is not None
    if option == "--passed":
        return text in ("true", "false")
    if option == "--lens":
        return _LENS_ID.fullmatch(text) is not None
    if option == "--verdict":
        return text in ("bears", "doubt")
    if option == "--sources":
        return _SOURCE_IDS.fullmatch(text) is not None
    if option == "--part":
        return _PART.fullmatch(text) is not None
    return option == "--by" and text == by


def _fits(command, commands, by):
    """True only for one of `commands` (subcommand: its options and its here-document or None), written the way the
    helper's file writes it: `radar` (or this plugin's own bin/radar), the subcommand, each of its options exactly
    once in any order (and those `OPTIONAL` gives it at most once: a `--part` only as a plain positive whole number),
    and, for a subcommand that takes one, the here-document opener last on the first line, the
    text, and the end mark alone on the last line. No line of the text may be the end mark. `--by` must be `by`.
    No --note, --file or --from-json: through them a helper could put outside text on the command line, set any
    option, or send a list with curly brackets, which would stop every call for an approval."""
    if not isinstance(command, str) or "\0" in command:
        return False
    if command.endswith("\n"):
        command = command[:-1]
    lines = command.split("\n")
    openers = tuple(here[0] for _, here in commands.values() if here)
    words = _words(lines[0], openers)
    if not words or len(words) < 2 or any((opener, False) in words[:-1] for opener in openers):
        return False
    program = words[0][0]
    if program != "radar" and not _is_own_radar(program):
        return False
    subcommand, quoted = words[1]
    if quoted or subcommand not in commands:
        return False
    needed, here = commands[subcommand]
    optional = OPTIONAL.get(subcommand, ())
    rest = words[2:]
    if here:
        opener, end = here
        if not rest or rest[-1] != (opener, False):
            return False
        if len(lines) < 2 or lines[-1] != end or end in lines[1:-1]:
            return False
        rest = rest[:-1]
    elif len(lines) != 1 or any((opener, False) in rest for opener in openers):
        return False
    seen = set()
    index = 0
    while index < len(rest):
        option, option_quoted = rest[index]
        if option_quoted or (option not in needed and option not in optional) or option in seen:
            return False
        seen.add(option)
        if option in SWITCHES:
            index += 1
            continue
        if index + 1 >= len(rest):
            return False
        text, text_quoted = rest[index + 1]
        if not _value_fits(option, text, text_quoted, by):
            return False
        index += 2
    return seen - set(optional) == set(needed)


def _is_a_checker_command(command):
    """True only for the two commands of the support checker, written the way its file writes them.

    record-support takes its note as plain text from a here-document (--note-stdin); never --note or --from-json,
    through which a helper could set any option."""
    return _fits(command, CHECKER_COMMANDS, CHECKER_BY)


def _is_a_lens_helper_command(helper, command):
    """True only for the two commands of the lens helper `helper`, written the way its file writes them: the advisor
    records its list as plain lines from its own here-document (--list-stdin), a reader its note as plain text from a
    here-document (--note-stdin), and each only under its own name, so one reader never records under the other's."""
    return _fits(command, LENS_COMMANDS[helper], helper)


def _is_a_grouper_command(command):
    """True only for the two commands of the project grouper, written the way its file writes them: it records its
    list as plain lines from a here-document (--list-stdin), never through a file, and only under its own name. A curly
    bracket anywhere in the call is refused too: with one, Claude Code may stop the call to ask the person, and the
    grouper is told to write none, so the refusal lets it correct the list and send it again."""
    if isinstance(command, str) and ("{" in command or "}" in command):
        return False
    return _fits(command, GROUPER_COMMANDS["project-grouper"], "project-grouper")


def _is_a_matcher_command(command):
    """True only for the two commands of the claim matcher, written the way its file writes them: it records its list
    as plain lines from a here-document (--list-stdin), never through a file, and only under its own name. A curly
    bracket anywhere in the call is refused too, as for the grouper."""
    if isinstance(command, str) and ("{" in command or "}" in command):
        return False
    return _fits(command, MATCHER_COMMANDS["claim-matcher"], "claim-matcher")


# ---------------------------------------------------------------- the decision

def _decide(event):
    tool = event.get("tool_name")
    if tool in WRITING_TOOLS:
        return _judge_write(event)
    if tool == "Bash":
        helper = _helper_name(event.get("agent_type"))
        tool_input = event.get("tool_input")
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if helper is None:
            # Rule 3. The one place where the guard judges a command of the lead (or of any agent that is not one of
            # this plugin's helpers): only the support checker records a verdict, only the two link readers record a
            # link verdict, only the lens advisor records the recommendation and only the project grouper records the
            # projects, so a command that holds one of these words anywhere (by a full path, through start_radar.py,
            # inside sh -c) is refused, with the sentence of the first of RECORD_WORDS that it holds. It is a catch
            # for slips, not a wall: a lead set on getting round it can, by spelling the word another way or by
            # running Python itself. The gate stays the real check.
            if not isinstance(command, str):
                return None
            for word, reason in RECORD_WORDS:
                if word in command:
                    return reason
            return None
        if helper == CHECKER:
            return None if _is_a_checker_command(command) else HELPER_REASON
        if helper in LENS_COMMANDS:
            return None if _is_a_lens_helper_command(helper, command) else LENS_REASONS[helper]
        if helper in GROUPER_COMMANDS:
            return None if _is_a_grouper_command(command) else GROUPER_REASON
        if helper in MATCHER_COMMANDS:
            return None if _is_a_matcher_command(command) else MATCHER_REASON
        return NO_COMMANDS_REASON
    return None


def _calls_a_helper(event):
    """Whether an event the guard could not judge comes from one of this plugin's helpers. Asked again without
    relying on what failed: when even _helper_name fails, any helper's name in agent_type counts."""
    try:
        agent_type = event.get("agent_type")
    except Exception:
        return False
    try:
        return _helper_name(agent_type) is not None
    except Exception:
        return any(name in str(agent_type) for name in HELPERS)


def decide(event):
    """The reason for refusing the call, or None to let it through. An error of the guard's own lets the call
    through, except a helper's call: a helper is never unlimited, so that is refused."""
    try:
        return _decide(event)
    except Exception:
        return FAILED_REASON if _calls_a_helper(event) else None


def main():
    try:
        reason = decide(json.loads(sys.stdin.buffer.read().decode("utf-8")))
    except Exception:
        reason = None
    if not reason:
        return 0
    try:
        sys.stderr.write(reason + "\n")
    except Exception:
        pass
    return 2


if __name__ == "__main__":
    sys.exit(main())
