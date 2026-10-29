"""PyInstaller entry point for the packaged CoCreate app."""

import os
import sys

# Vendored + app packages live at the bundle root.
sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[0])))

from cocreation.server import main

if __name__ == "__main__":
    main()
