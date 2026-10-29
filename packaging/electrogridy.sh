#!/usr/bin/python3
import sys

sys.path.insert(0, "/usr/share/electrogridy")

from electrogridy.app import main  # noqa: E402

sys.exit(main())
