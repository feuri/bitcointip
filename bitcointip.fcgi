#!/usr/bin/env python3

import sys
sys.path.insert(0, "$HOME/bitcointip")

from wsgiref.handlers import CGIHandler
from bitcointip import app

if __name__ == '__main__':
    CGIHandler().run(app)
