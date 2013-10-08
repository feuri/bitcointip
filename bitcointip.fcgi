#!/usr/bin/env python3

import sys
sys.path.insert(0, "$HOME/bitcointip")

from flup.server.fcgi import WSGIServer
from bitcointip import app

if __name__ == '__main__':
    WSGIServer(app).run()
