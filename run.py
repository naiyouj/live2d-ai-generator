# -*- coding: utf-8 -*-
"""启动入口：python run.py（或双击 启动.bat）"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from server.main import main  # noqa: E402

if __name__ == "__main__":
    main()
