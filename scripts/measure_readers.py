"""Measure the two link readers on planted links. WRITTEN, NOT RUN: it needs a model session and costs money.

Test layer 3 of the lens recommender's design. The fixture `tests/fixtures/planted_links.json` is invented and says so:
three illustrative lenses, fourteen illustrative facts and 24 links, half of them right (the fact bears on one of the
lens's three questions) and half wrong. Each link is also marked `plain` or `subtle`. This script gives each of the
two readers (`lens-link-reader` and `lens-link-reader-quick`) the same packets that `radar lens-link-context` gives
them, with the reader's own helper file as its instructions and the model that `settings/models.json` sets for it, and
counts, for each reader and for the pair:

- how many wrong links it marked with a doubt (caught), out of all wrong links;
- how many right links it marked with a doubt (marked by mistake), out of all right links;
- how many links it gave no usable verdict for.

For the pair, a link is marked when at least one reader doubts it, which is what the first stop shows.

Run as `python3 scripts/measure_readers.py`: without `--run` it only prints what it would do and what that would roughly
cost (an estimate), and calls nothing. Only `--run`, given by the person who pays, starts the model sessions: one for
each reader and each repeat. A model can answer differently another time, so the counts are an indication of how a
reader behaves on these 24 links, not proof, and the report may not claim more than they show. Standard library only.

The way the model is started (the `claude` command with `--model`, `--tools ""` for no tools, `--append-system-prompt`
and `--output-format json`) follows Claude Code's documented options but was never tried here: if a first run is
refused, only `claude_command` needs to change.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "planted_links.json"
READERS = ("lens-link-reader", "lens-link-reader-quick")
MODELS_FILE = ROOT / "settings" / "models.json"
VERDICTS = ("bears", "doubt")
PACKET_KEYS = ("lens", "lens_name", "idea", "suggests", "questions", "fact", "statement", "status")
# Guessed sizes for the estimate only: tokens in and out for one reader's session over 24 links.
ESTIMATE_TOKENS_IN = 9000
ESTIMATE_TOKENS_OUT = 2500
ESTIMATE_PRICE = {"opus": (4.0, 20.0), "sonnet": (2.0, 10.0)}   # US dollars per million tokens, list prices of 2026-11-03

MEASUREMENT_NOTE = """This is a measurement of how you judge, not a run. Ignore every part of your instructions that tells you to run a command or to record anything: you have no tools. The packets that the first command would give you are below, as one JSON object. Judge each one by the rules above, on its own. Answer with exactly one line for each packet, in the order given, and nothing else:

<lens> <fact> <bears or doubt> <your note, one sentence, on the same line>

The lens is the packet's `lens` and the fact is its `fact`, copied exactly."""


class MeasurementError(Exception):
    """Something this script cannot go on from; the text says what, in plain words."""


def load_fixture(path: Path = FIXTURE) -> dict:
    """The fixture, checked: it must say it is illustrative, and every link must name a lens and a fact it holds."""
    try:
        fixture = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MeasurementError(f"The fixture cannot be read: {error}") from error
    if not isinstance(fixture, dict) or fixture.get("illustrative") is not True:
        raise MeasurementError("The fixture must be a JSON object marked as illustrative.")
    lens_ids = {lens["id"] for lens in fixture["lenses"]}
    fact_ids = {fact["id"] for fact in fixture["facts"]}
    for link in fixture["links"]:
        if link["lens"] not in lens_ids or link["fact"] not in fact_ids:
            raise MeasurementError(f"A link names a lens or a fact the fixture does not hold: {link}")
    return fixture


def packets(fixture: dict) -> list:
    """One packet for each link, with the keys `radar lens-link-context` prints and nothing of the link's answer."""
    lenses = {lens["id"]: lens for lens in fixture["lenses"]}
    facts = {fact["id"]: fact for fact in fixture["facts"]}
    found = []
    for link in fixture["links"]:
        lens, fact = lenses[link["lens"]], facts[link["fact"]]
        found.append({"lens": lens["id"], "lens_name": lens["name"], "idea": lens["idea"], "suggests": lens["suggests"],
                      "questions": list(lens["questions"]), "fact": fact["id"], "statement": fact["statement"],
                      "status": fact["status"]})
    return found


def reader_instructions(reader: str, root: Path = ROOT) -> str:
    """The body of the reader's helper file, without its front matter, followed by the note for a measurement."""
    text = (Path(root) / "agents" / f"{reader}.md").read_text(encoding="utf-8")
    body = re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.S)
    return body.strip() + "\n\n" + MEASUREMENT_NOTE


def reader_prompt(found: list) -> str:
    return json.dumps({"packets": found}, indent=2)


def models_set_to(root: Path = ROOT) -> dict:
    try:
        models = json.loads((Path(root) / "settings" / "models.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MeasurementError(f"settings/models.json cannot be read: {error}") from error
    missing = [reader for reader in READERS if not isinstance(models.get(reader), str)]
    if missing:
        raise MeasurementError(f"settings/models.json sets no model for {', '.join(missing)}.")
    return {reader: models[reader] for reader in READERS}


def claude_command(model: str, instructions: str) -> list:
    """The command that starts one reader's session. The prompt goes in on standard input."""
    return ["claude", "-p", "--model", model, "--tools", "", "--append-system-prompt", instructions,
            "--output-format", "json"]


def parse_verdicts(answer: str) -> dict:
    """`{(lens, fact): "bears" or "doubt"}` from the reader's lines `<lens> <fact> <verdict> <note>`. A line that does not
    follow the form is left out, so its link counts as no usable verdict; a link answered twice with different
    verdicts counts as none."""
    found, clashing = {}, set()
    for line in answer.splitlines():
        match = re.match(r"\s*`?([A-Za-z0-9_-]+)`?\s+`?(F[0-9]+)`?\s+`?(bears|doubt)`?(?:\W|$)", line)
        if not match:
            continue
        key, verdict = (match.group(1), match.group(2)), match.group(3)
        if key in found and found[key] != verdict:
            clashing.add(key)
        found[key] = verdict
    return {key: verdict for key, verdict in found.items() if key not in clashing}


def _rate(marked: int, total: int) -> str:
    return f"{marked} of {total}"


def score(fixture: dict, verdicts: dict) -> dict:
    """The counts for each reader and for the pair. `verdicts` is `{reader: {(lens, fact): verdict}}`.

    For a reader: `wrong_caught` and `right_marked` as counts, `no_verdict` as the number of links without a usable
    verdict, each also split by `plain` and `subtle`. A link without a verdict is never counted as a doubt and never as
    agreement. For the pair (`pair`): a link is marked when at least one reader doubts it; it has no verdict only when
    neither reader gave one."""
    links = fixture["links"]
    wrong = [link for link in links if not link["right"]]
    right = [link for link in links if link["right"]]

    def count(verdict_of, group, wanted) -> dict:
        out = {"all": 0, "plain": 0, "subtle": 0}
        for link in group:
            if verdict_of(link) == wanted:
                out["all"] += 1
                out[link["kind"]] += 1
        return out

    def totals(group) -> dict:
        return {"all": len(group), "plain": sum(l["kind"] == "plain" for l in group),
                "subtle": sum(l["kind"] == "subtle" for l in group)}

    result = {"wrong_links": totals(wrong), "right_links": totals(right)}
    views = {reader: (lambda link, reader=reader: verdicts.get(reader, {}).get((link["lens"], link["fact"])))
             for reader in READERS}

    def pair(link):
        given = [views[reader](link) for reader in READERS if views[reader](link)]
        if not given:
            return None
        return "doubt" if "doubt" in given else "bears"

    views["pair"] = pair
    for name, verdict_of in views.items():
        result[name] = {"wrong_caught": count(verdict_of, wrong, "doubt"),
                        "right_marked": count(verdict_of, right, "doubt"),
                        "no_verdict": sum(verdict_of(link) is None for link in links)}
    return result


def report(result: dict) -> str:
    """The counts in plain words, one block for each reader and one for the pair."""
    lines = []
    wrong, right = result["wrong_links"], result["right_links"]
    for name in (*READERS, "pair"):
        part = result[name]
        title = "The pair (a link is marked when at least one reader doubts it)" if name == "pair" else name
        lines += [title,
                  f"  wrong links it marked: {_rate(part['wrong_caught']['all'], wrong['all'])} "
                  f"(plain {_rate(part['wrong_caught']['plain'], wrong['plain'])}, "
                  f"subtle {_rate(part['wrong_caught']['subtle'], wrong['subtle'])})",
                  f"  right links it marked by mistake: {_rate(part['right_marked']['all'], right['all'])} "
                  f"(plain {_rate(part['right_marked']['plain'], right['plain'])}, "
                  f"subtle {_rate(part['right_marked']['subtle'], right['subtle'])})",
                  f"  links with no usable verdict: {part['no_verdict']}"]
    lines.append("An indication on 24 invented links, not proof: a model can answer differently another time.")
    return "\n".join(lines)


def estimate_cost(model: str, repeats: int) -> float:
    """A rough cost in US dollars of one reader over `repeats` sessions, from guessed sizes. An estimate only."""
    family = "sonnet" if "sonnet" in model else "opus"
    price_in, price_out = ESTIMATE_PRICE[family]
    return repeats * (ESTIMATE_TOKENS_IN * price_in + ESTIMATE_TOKENS_OUT * price_out) / 1_000_000


def run_session(command: list, prompt: str) -> str:
    """Start one session with `command`, send `prompt`, and return the answer text. The model is the only costly part."""
    try:
        done = subprocess.run(command, input=prompt, capture_output=True, text=True, timeout=1800, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MeasurementError(f"The session could not be run: {error}") from error
    if done.returncode != 0:
        raise MeasurementError(f"The session ended with exit code {done.returncode}: {done.stderr.strip()[:400]}")
    try:
        answer = json.loads(done.stdout)
    except ValueError:
        return done.stdout
    return answer.get("result", "") if isinstance(answer, dict) and isinstance(answer.get("result"), str) else done.stdout


def measure(fixture: dict, repeats: int, session=run_session, root: Path = ROOT) -> dict:
    """Run each reader `repeats` times and score the readings of each repeat. `session(command, prompt)` returns the text."""
    models = models_set_to(root)
    found = packets(fixture)
    runs = []
    for _ in range(repeats):
        verdicts = {}
        for reader in READERS:
            answer = session(claude_command(models[reader], reader_instructions(reader, root)), reader_prompt(found))
            verdicts[reader] = parse_verdicts(answer)
        runs.append(score(fixture, verdicts))
    return {"models_set_to": models, "repeats": repeats, "runs": runs}


def main(argv=None, session=run_session) -> int:
    parser = argparse.ArgumentParser(description="Measure the two link readers on planted links (costs money; needs --run).")
    parser.add_argument("--run", action="store_true", help="start the model sessions; without it nothing is called")
    parser.add_argument("--repeats", type=int, default=1, help="how many times each reader reads all links (default 1)")
    parser.add_argument("--fixture", default=str(FIXTURE), help="the fixture of planted links")
    parser.add_argument("--json", action="store_true", help="print the counts as JSON instead of words")
    args = parser.parse_args(argv)
    if args.repeats < 1:
        print("--repeats must be at least 1.", file=sys.stderr)
        return 2
    try:
        fixture = load_fixture(Path(args.fixture))
        models = models_set_to()
        if not args.run:
            cost = sum(estimate_cost(models[reader], args.repeats) for reader in READERS)
            print(f"Nothing was called. With --run this would start {len(READERS) * args.repeats} model session(s): "
                  f"{', '.join(f'{reader} on {models[reader]}' for reader in READERS)}, each reading "
                  f"{len(fixture['links'])} invented links ({sum(l['right'] for l in fixture['links'])} right, "
                  f"{sum(not l['right'] for l in fixture['links'])} wrong). A rough estimate of the cost: about "
                  f"{cost:.2f} US dollars (guessed sizes, not measured).")
            return 0
        result = measure(fixture, args.repeats, session)
    except MeasurementError as error:
        print(str(error), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for number, run in enumerate(result["runs"], 1):
            print(f"Read {number} of {result['repeats']}, models set to {json.dumps(result['models_set_to'])}")
            print(report(run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
