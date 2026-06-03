from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from exam_simulator.gui import App
else:
    from .gui import App


if __name__ == "__main__":
    App().mainloop()
