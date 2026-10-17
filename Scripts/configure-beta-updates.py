#!/usr/bin/env python3
"""Seal beta policy before signing, or inspect the packaged Sparkle code paths."""
import argparse
from pathlib import Path
from beta_updates import policy, seal, validate_framework

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("command", choices=("seal", "sign-list"))
parser.add_argument("--app", type=Path, required=True)
parser.add_argument("--tag")
args = parser.parse_args()
config = policy()
if args.command == "seal":
    seal(args.app, config, args.tag)
else:
    for path in validate_framework(args.app, config):
        print(path)
