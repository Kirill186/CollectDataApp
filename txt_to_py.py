#!/usr/bin/env python3
"""Generate .py drafts from pseudocode .txt files."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import List


IMPORT_RE = re.compile(r"^-\s+(import\s+.+|from\s+.+\s+import\s+.+)$")
NAME_RE = re.compile(r"^-\s+([A-Za-z_][A-Za-z0-9_]*)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert pseudocode txt files into python drafts")
    parser.add_argument("--ai-root", required=True, help="Path to raw/ai/<repo>")
    parser.add_argument("--replace", action="store_true", help="Delete .txt files after generating .py")
    return parser.parse_args()


def parse_sections(text: str) -> tuple[List[str], List[str], List[str], List[str]]:
    imports: List[str] = []
    classes: List[str] = []
    functions: List[str] = []
    steps: List[str] = []

    mode = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("1) Точные импорты"):
            mode = "imports"
            continue
        if line.startswith("2) Основные сущности"):
            mode = "entities"
            continue
        if line == "Классы:":
            mode = "classes"
            continue
        if line == "Функции:":
            mode = "functions"
            continue
        if line.startswith("3) Псевдокод"):
            mode = "steps"
            continue
        if line.startswith("4) Ограничения"):
            mode = ""
            continue

        if mode == "imports":
            m = IMPORT_RE.match(line)
            if m:
                imports.append(m.group(1))
        elif mode == "classes":
            m = NAME_RE.match(line)
            if m:
                classes.append(m.group(1))
        elif mode == "functions":
            m = NAME_RE.match(line)
            if m:
                functions.append(m.group(1))
        elif mode == "steps" and line.startswith("-"):
            steps.append(line[1:].strip())

    return imports, classes, functions, steps


def build_python(imports: List[str], classes: List[str], functions: List[str], steps: List[str]) -> str:
    chunks: List[str] = []
    chunks.append('"""AI-generated draft from pseudocode specification."""\n')

    if imports:
        chunks.append("\n".join(imports))
    else:
        chunks.append("# TODO: add imports based on project context")

    chunks.append("")
    chunks.append("# Реализовать шаги:")
    if steps:
        chunks.extend([f"# - {step}" for step in steps])
    else:
        chunks.append("# - TODO: define implementation steps")

    for class_name in classes:
        chunks.append("")
        chunks.append(f"class {class_name}:")
        chunks.append("    def __init__(self) -> None:")
        chunks.append("        # TODO: initialize state")
        chunks.append("        pass")

    for func_name in functions:
        chunks.append("")
        chunks.append(f"def {func_name}(*args, **kwargs):")
        chunks.append("    # TODO: implement function logic")
        chunks.append("    raise NotImplementedError")

    return "\n".join(chunks).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    ai_root = Path(args.ai_root).resolve()

    for txt_file in sorted(ai_root.rglob("*.txt")):
        if txt_file.name == "PROMPT.txt":
            continue

        imports, classes, functions, steps = parse_sections(txt_file.read_text(encoding="utf-8", errors="ignore"))
        py_target = txt_file.with_suffix(".py")
        py_target.write_text(build_python(imports, classes, functions, steps), encoding="utf-8")

        if args.replace:
            txt_file.unlink()

    print(f"Done. Generated python drafts in: {ai_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
