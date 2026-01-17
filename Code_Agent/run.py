#!/usr/bin/env python3
"""
MAEUM_CODE

python run.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from CUSTOM.cli import main

if __name__ == "__main__":
    main()
