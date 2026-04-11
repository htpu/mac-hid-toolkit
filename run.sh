#!/bin/bash
cd "$(dirname "$0")"
exec .venv/bin/python3 -u remote_control.py --config config.json
