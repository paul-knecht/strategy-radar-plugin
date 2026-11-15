#!/bin/sh
# Runs the three test cases of this folder against the plugin in this repository.
# Every run is a real model session on the account of whoever starts it.
# Extra arguments are passed on, for example: sh evals/run.sh --case starts-a-run --runs 1
# The result page is never uploaded: the option that would turn that on is refused, in any spelling that starts
# with --pub (a shortened option is read as the whole one).
for argument in "$@"; do
  case "$argument" in
    --pub*)
      echo "evals/run.sh does not upload the result page, so $argument is not allowed." >&2
      exit 2
      ;;
  esac
done
cd "$(dirname "$0")/.." || exit 2
exec claude plugin eval . --ablation none --no-publish --trust-plugin --threshold 1.0 "$@"
