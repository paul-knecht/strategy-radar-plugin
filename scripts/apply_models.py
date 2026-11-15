"""Write the model choices of settings/models.json into the front matter of agents/<name>.md.

Run as `python3 scripts/apply_models.py`. Standard library only.
"""
import json
import re
import sys
from pathlib import Path

MODEL_LINE = re.compile(r"^model:[^\r\n]*", re.M)
# A model value is one plain word: a line break or any other character could write more into a helper's front matter.
MODEL_VALUE = re.compile(r"[A-Za-z0-9._:-]+")


def apply(root: Path) -> list:
    """Rewrite the `model:` line of each helper file from the settings; return the names that changed."""
    root = Path(root)
    settings = json.loads((root / "settings" / "models.json").read_text(encoding="utf-8"))
    files = {path.stem: path for path in sorted((root / "agents").glob("*.md"))}
    missing_setting = sorted(set(files) - set(settings))
    missing_file = sorted(set(settings) - set(files))
    if missing_setting:
        raise ValueError("no model is set for: " + ", ".join(missing_setting))
    if missing_file:
        raise ValueError("a model is set but there is no helper file for: " + ", ".join(missing_file))
    for name, value in settings.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError("the model for " + name + " must be text, such as sonnet")
        if not MODEL_VALUE.fullmatch(value):
            raise ValueError("the model for " + name + " may hold only the letters a to z, digits and . _ : -, "
                             "such as sonnet")
    changed = []
    for name, path in files.items():
        with open(path, encoding="utf-8", newline="") as handle:   # newline="" keeps the line endings as they are
            text = handle.read()
        ending = "\r\n" if "\r\n" in text else "\n"
        head, sep, rest = text.partition(ending + "---" + ending)
        if not text.startswith("---" + ending) or not sep or not MODEL_LINE.search(head):
            raise ValueError(name + " has no model line in its front matter")
        new_head = MODEL_LINE.sub("model: " + settings[name], head, count=1)
        if new_head != head:
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(new_head + sep + rest)
            changed.append(name)
    return changed


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    try:
        changed = apply(root)
    except ValueError as problem:
        print("error: " + str(problem), file=sys.stderr)
        return 1
    print(json.dumps({"changed": changed}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
