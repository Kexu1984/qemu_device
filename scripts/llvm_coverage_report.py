#!/usr/bin/env python3
"""Generate LLVM coverage reports from a KXCV MMIO coverage dump."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


DEFAULT_OBJECTS = [
    'build/main.o',
    'build/cpu1_main.o',
    'build/runtime.o',
]

DEFAULT_SOURCES = [
    'firmware/main.c',
    'firmware/cpu1_main.c',
    'firmware/runtime.c',
]


def run(cmd: list[str], *, stdout_path: Path | None = None) -> None:
    print('+ ' + ' '.join(cmd))
    if stdout_path is None:
        subprocess.run(cmd, check=True)
        return
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open('w', encoding='utf-8') as fh:
        subprocess.run(cmd, check=True, stdout=fh)


def object_args(objects: list[str]) -> list[str]:
    if not objects:
        raise ValueError('at least one object file is required')
    args = [objects[0]]
    for obj in objects[1:]:
        args.extend(['-object', obj])
    return args


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dump', default='build/coverage/firmware.kxcv')
    parser.add_argument('--elf', default='build/firmware.elf')
    parser.add_argument('--profraw', default='build/coverage/firmware.profraw')
    parser.add_argument('--profdata', default='build/coverage/firmware.profdata')
    parser.add_argument('--summary', default='build/coverage/llvm_cov_report.txt')
    parser.add_argument('--html-dir', default='build/coverage/html')
    parser.add_argument('--object', action='append', dest='objects', help='Coverage object file; may be repeated')
    parser.add_argument('--source', action='append', dest='sources', help='Source file to include; may be repeated')
    parser.add_argument('--no-html', action='store_true')
    args = parser.parse_args()

    objects = args.objects or DEFAULT_OBJECTS
    sources = args.sources or DEFAULT_SOURCES
    for path in [args.dump, args.elf, *objects, *sources]:
        if not Path(path).exists():
            print(f'ERROR: required file not found: {path}', file=sys.stderr)
            return 1

    try:
        run(['scripts/kxcv_to_profraw.py', args.dump, '-o', args.profraw, '--elf', args.elf])
        run(['llvm-profdata', 'merge', '-sparse', args.profraw, '-o', args.profdata])

        base = object_args(objects)
        run(
            ['llvm-cov', 'report', *base, f'-instr-profile={args.profdata}', *sources],
            stdout_path=Path(args.summary),
        )
        run(
            ['llvm-cov', 'show', *base, f'-instr-profile={args.profdata}', '-format=text', *sources],
            stdout_path=Path('build/coverage/llvm_cov_show.txt'),
        )
        if not args.no_html:
            run([
                'llvm-cov', 'show', *base,
                f'-instr-profile={args.profdata}',
                '-format=html',
                f'-output-dir={args.html_dir}',
                *sources,
            ])
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1

    print(f'coverage summary: {args.summary}')
    print('line report: build/coverage/llvm_cov_show.txt')
    if not args.no_html:
        print(f'html report: {args.html_dir}/index.html')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())