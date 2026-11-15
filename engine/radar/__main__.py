"""`python -m radar`: the engine run as a module, for working on it. The launcher `bin/radar` does not use it: it starts
`engine/start_radar.py` as a script file, so the folder the command is run from is never searched for a `radar`."""
import sys

from .cli import main

sys.exit(main())
