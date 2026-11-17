"""Check that no run of eight or more words of a lens's own words stands in a copy of a work.

Run as `python3 scripts/check_lens_overlap.py --lens FILE --copies FOLDER`. Standard library only. The maintainer's
`new-lens` skill runs it on a draft lens and on the copies folder of the private evidence run, where the program keeps
the readable text of each copy as a `.txt` file; the original files beside them (a PDF, a web page) are not read.

The lens's own words are its name, idea, suggests, limits, competing idea and questions. Its references are left out:
a reference names a work as the work names itself, and that is no passage of it.

Words are compared in lower case, as runs of letters and digits; every other sign counts as a gap between words. Each
lens text and each copy is taken on its own, so a run is never made across two texts. Where runs found in a lens text
overlap or touch, they are given once, as one longer stretch made of those runs; the stretch as a whole need not stand
in a copy.

Exit codes: 0 no run found; 1 at least one run found (each is printed); 2 used wrongly (a lens file that cannot be read
or is not a JSON object, a copies folder that is missing or holds no `.txt` file). A wrong use is never a pass.
"""
import argparse
import json
import re
import sys
from pathlib import Path

WORDS = 8
LENS_TEXTS = ("name", "idea", "suggests", "limits", "competing_idea")
LENS_LISTS = ("questions",)
COPY_ENDING = ".txt"
_WORD = re.compile(r"[^\W_]+")


def words_of(text: str) -> list:
    """The words of a text in lower case: runs of letters and digits."""
    return _WORD.findall(text.lower())


def _runs(words: list, size: int) -> set:
    return {tuple(words[i:i + size]) for i in range(len(words) - size + 1)}


def overlap(lens_texts: list, copy_texts: list, words: int = WORDS) -> list:
    """Every stretch of a lens text made of runs of `words` consecutive words that each stand in a copy.

    Case and punctuation are ignored on both sides. Runs found in one lens text that overlap or touch are joined into
    one stretch, so a stretch longer than `words` is made of runs found in a copy but need not stand in a copy as a
    whole (two runs may come from two places or two copies). Each stretch is given once, in the order of the lens texts.
    """
    if not isinstance(words, int) or isinstance(words, bool) or words < 1:
        raise ValueError("words must be a whole number of at least 1")
    in_copies = set()
    for copy in copy_texts:
        in_copies |= _runs(words_of(copy), words)
    found = []
    for text in lens_texts:
        lens_words = words_of(text)
        hits = [i for i in range(len(lens_words) - words + 1) if tuple(lens_words[i:i + words]) in in_copies]
        stretches = []
        for i in hits:
            if stretches and i <= stretches[-1][1]:
                stretches[-1][1] = i + words
            else:
                stretches.append([i, i + words])
        for start, end in stretches:
            stretch = " ".join(lens_words[start:end])
            if stretch not in found:
                found.append(stretch)
    return found


def lens_texts(lens: dict) -> list:
    """The lens's own words: its texts and its questions, never its references."""
    texts = [lens[key] for key in LENS_TEXTS if isinstance(lens.get(key), str)]
    for key in LENS_LISTS:
        if isinstance(lens.get(key), list):
            texts.extend(item for item in lens[key] if isinstance(item, str))
    return texts


def _wrong(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check that no run of 8 or more words of a lens stands in a copy.")
    parser.add_argument("--lens", required=True, help="the lens file to check")
    parser.add_argument("--copies", required=True, help="the folder that holds the copies (.txt files, also below it)")
    args = parser.parse_args(argv)
    try:
        lens = json.loads(Path(args.lens).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return _wrong(f"The lens file cannot be read as JSON: {error}")
    if not isinstance(lens, dict):
        return _wrong("The lens file must hold one JSON object.")
    folder = Path(args.copies)
    if not folder.is_dir():
        return _wrong("The copies folder does not exist or is not a folder.")
    paths = sorted(p for p in folder.rglob("*" + COPY_ENDING) if p.is_file())
    if not paths:
        return _wrong("The copies folder holds no .txt copy, so there is nothing to compare the lens with.")
    try:
        copies = [p.read_text(encoding="utf-8", errors="replace") for p in paths]
    except OSError as error:
        return _wrong(f"A copy cannot be read: {error}")
    found = overlap(lens_texts(lens), copies)
    if not found:
        print(f"No run of {WORDS} or more words of the lens stands in any of the {len(paths)} copies.")
        return 0
    print(f"{len(found)} stretch(es) of the lens made of runs of {WORDS} or more words that stand in a copy. "
          "Reword each in our own words:")
    for stretch in found:
        print("- " + stretch)
    return 1


if __name__ == "__main__":
    sys.exit(main())
