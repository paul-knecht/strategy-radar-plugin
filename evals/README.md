# Test cases: does the right skill start

These three cases start real model sessions with only this plugin loaded. Each one checks a single thing: which skill, if any, the session started. They do not check what the skill then did; the whole-run tests do that.

| Case | The person says | What must happen |
| :- | :- | :- |
| `starts-a-run` | A question about which competitors of an invented company are adding filling capacity, using the demo pack | The `strategy-radar:run` skill starts |
| `starts-the-guided-start` | They have just installed Strategy Radar and want help getting started | The `strategy-radar:start` skill starts |
| `stays-out-of-other-work` | Rename a function in a Python file and update its callers | No Strategy Radar skill starts |

Each case runs three times and all three runs must pass.

The third case checks the intent of one request only: a request to change code, which has nothing to do with Strategy Radar, starts none of its skills. It says nothing about other kinds of request.

## Run them

From the repository root:

```
sh evals/run.sh
```

The script holds this command, and passes any extra arguments on (for example `--case starts-a-run --runs 1` to try one case once):

```
claude plugin eval . --ablation none --no-publish --trust-plugin --threshold 1.0
```

- `--no-publish` is required. Without it the result page is uploaded to claude.ai. The script refuses the option that would turn the upload on, in every spelling that starts with `--pub`.
- `--ablation none` runs the plugin only, so the check on which skill started counts towards the score.
- `--trust-plugin` answers the question "Do you trust this plugin folder?" in advance, so the run does not stop to ask; use it only on a plugin you wrote or have read.
- `--threshold 1.0` means a case passes only when all three of its runs pass.
- The command ends with exit code 0 when every case passes.

Most runs end with a line saying the session reached its turn limit. That is expected with a limit of three turns and is not a failure: the check only needs to see which skill started, and that happens in the first turns.

## What it costs

Every run is a real model call on the account of whoever runs it. The suite is nine sessions (three cases, three runs each). Run it when a skill's description changes, not on every edit.

## Results

Results are written to `evals/results/`, one folder per run of the suite, with a report you can open in a browser. That folder is kept out of git.
