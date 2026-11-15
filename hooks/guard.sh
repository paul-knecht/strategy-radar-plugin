#!/bin/sh
# Starts the guard (guard.py, next to this file) with a Python 3.8 or newer and hands back its answer unchanged.
# It looks where bin/radar looks, in the same order: $RADAR_PYTHON, the private environment made by
# `radar setup`, then python3. A python3 that is there but does not work is passed over, and so is Apple's
# stand-in /usr/bin/python3 on a Mac without the developer tools (see may_try).
# After that it tries python3.14 down to python3.8 and python, so the guard stays on where it can.
# With no Python at all the call is let through: the radar program cannot run there either.
# The same when guard.py is not there. But a call of one of the plugin's helpers is refused then (see
# not_started): a helper is never unlimited, even when the guard cannot start. Python is started with -I,
# so no PYTHON... setting of the computer and no file lying next to the guard or in the session's folder
# can change what it does. Only shell built-ins are used, so the script works with any PATH.
# not_started: the guard cannot start. The event is read line by line, and when its text names one of the
# plugin's helpers (as a JSON text of its own, plain or with the plugin's name) the call is refused.
not_started() {
  event=
  while IFS= read -r line || [ -n "$line" ]; do event="$event$line"; done
  case "$event" in
    *'"support-checker"'*|*'"source-scout"'*|*'"fact-extractor"'*|*'"bias-auditor"'*|\
    *'"strategy-radar:support-checker"'*|*'"strategy-radar:source-scout"'*|\
    *'"strategy-radar:fact-extractor"'*|*'"strategy-radar:bias-auditor"'*)
      refusal="Strategy Radar's guard: The guard cannot start on this computer, so the helpers of Strategy Radar may not use this tool now. Install Python from python.org, or install the plugin again."
      printf '%s\n' "$refusal" >&2
      exit 2 ;;
  esac
  exit 0
}
case "$0" in */*) dir=${0%/*} ;; *) dir=. ;; esac
here=$(CDPATH= cd -- "$dir" 2>/dev/null && pwd) || not_started
[ -f "$here/guard.py" ] && [ -r "$here/guard.py" ] || not_started
new_enough() { "$1" -I -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' </dev/null >/dev/null 2>&1; }
# On a Mac, /usr/bin/python3 is only a stand-in until Apple's developer tools are installed, and starting it offers
# to install them. So there it is passed over unless the tools are there. Any other Python may be tried.
may_try() {
  [ "$1" = /usr/bin/python3 ] || return 0
  [ -e /System/Library/CoreServices/SystemVersion.plist ] || return 0
  [ -e /Library/Developer/CommandLineTools/usr/bin/python3 ] || [ -e /Applications/Xcode.app ]
}
for candidate in "$RADAR_PYTHON" "${RADAR_HOME:-$HOME/.strategy-radar}/venv/bin/python" python3; do
  if [ -n "$candidate" ] && may_try "$(command -v "$candidate")" && new_enough "$candidate"; then
    exec "$candidate" -I "$here/guard.py"
  fi
done
for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3.8 python; do
  if may_try "$(command -v "$candidate")" && new_enough "$candidate"; then
    exec "$candidate" -I "$here/guard.py"
  fi
done
not_started
