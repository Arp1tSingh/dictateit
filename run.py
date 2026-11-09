"""PyInstaller / double-click entry point.

`dictateit/main.py` uses relative imports (it is part of the package),
so the frozen exe launches through this file instead:

    python run.py --input notes.txt --ui
"""

import sys

from dictateit.main import main

if __name__ == "__main__":
    sys.exit(main())
