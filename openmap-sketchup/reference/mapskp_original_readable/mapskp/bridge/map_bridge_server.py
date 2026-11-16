# -*- coding: utf-8 -*-
import os
import sys
import mapskp_armor

_mbs = mapskp_armor.load_core_runtime(os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__":
    raise SystemExit(_mbs.main_cli(sys.argv[1:]))
