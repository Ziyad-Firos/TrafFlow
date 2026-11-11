#!/usr/bin/env python
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.config.settings")

from django.core.management import execute_from_command_line

execute_from_command_line(sys.argv)
