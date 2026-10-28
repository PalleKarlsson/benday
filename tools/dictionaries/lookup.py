#!/usr/bin/env python3
"""Looks words up in a StarDict dictionary (a spot check of a build).

  tool/dictionaries/lookup.py build/dictionaries/wiktionary-sv-*/benday-wiktionary-sv.ifo hus gick
  tool/dictionaries/lookup.py --text … (HTML shown as plain text)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stardict import StarDict  # noqa: E402


def as_text(html: str) -> str:
    t = re.sub(r'<li>', '\n  • ', html)
    t = re.sub(r'</p>|<br>', '\n    ', t)
    t = re.sub(r'<[^>]+>', '', t)
    return re.sub(r'&lt;', '<', re.sub(r'&gt;', '>',
                  re.sub(r'&amp;', '&', t))).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('ifo', type=Path)
    ap.add_argument('words', nargs='+')
    ap.add_argument('--text', action='store_true')
    ap.add_argument('--max', type=int, default=600,
                    help='characters per article (0: all)')
    args = ap.parse_args()
    d = StarDict(args.ifo)
    for w in args.words:
        hits = d.lookup(w)
        print(f'== {w}: {len(hits)} hit(s)')
        for head, body in hits:
            body = as_text(body) if args.text else body
            if args.max and len(body) > args.max:
                body = body[:args.max] + ' […]'
            print(f'-- {head}\n{body}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
