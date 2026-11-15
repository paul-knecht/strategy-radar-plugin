"""Started by `bin/radar` as a script file. Python puts this file's folder first on its search path, so the engine's
`radar` package is found here, and the folder the command is run from is not searched."""
import sys

from radar.cli import main

sys.exit(main())
