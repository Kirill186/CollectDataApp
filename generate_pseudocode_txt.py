#!/usr/bin/env python3
"""Generate detailed pseudocode `.txt` specs from Python source files."""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class FileMapping:
    source_relpath: str
    human_flat_file: str
    ai_txt_file: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate pseudocode txt files for AI dataset")
    parser.add_argument("--work-root", required=True, help="Path to checked out source repo")
    parser.add_argument("--ai-root", required=True, help="Path where .txt files should be created")
    parser.add_argument("--mapping-file", required=True, help="JSON file with source->flat-file mapping")
    return parser.parse_args()


def load_mappings(mapping_file: Path) -> List[FileMapping]:
    raw = json.loads(mapping_file.read_text(encoding="utf-8"))
    result: List[FileMapping] = []
    for item in raw:
        result.append(
            FileMapping(
                source_relpath=item["source_relpath"],
                human_flat_file=item["human_flat_file"],
                ai_txt_file=item["ai_txt_file"],
            )
        )
    return result


def extract_import_lines(source: str) -> List[str]:
    lines: List[str] = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            lines.append(stripped)
    return lines[:40]


def extract_structure(source: str) -> tuple[List[str], List[str], List[str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], [], []

    classes: List[str] = []
    functions: List[str] = []
    steps: List[str] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.append(node.name)
            methods = [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
            if methods:
                steps.append(f"Класс {node.name}: методы -> {', '.join(methods[:12])}")
            else:
                steps.append(f"Класс {node.name}: добавить минимум __init__ и один рабочий метод")
        elif isinstance(node, ast.FunctionDef):
            functions.append(node.name)
            args = [a.arg for a in node.args.args]
            steps.append(f"Функция {node.name}({', '.join(args)}): сохранить назначение и поток данных")

    return classes[:20], functions[:40], steps[:80]


def build_txt_content(mapping: FileMapping, imports: List[str], classes: List[str], functions: List[str], steps: List[str]) -> str:
    imports_block = "\n".join(f"- {line}" for line in imports) if imports else "- (импорты не обнаружены)"
    classes_block = "\n".join(f"- {name}" for name in classes) if classes else "- (классы не обнаружены)"
    functions_block = "\n".join(f"- {name}" for name in functions) if functions else "- (функции не обнаружены)"
    steps_block = "\n".join(f"- {item}" for item in steps) if steps else "- Определи минимальный каркас модуля и совместимые точки входа"

    return (
        f"Файл-источник: {mapping.source_relpath}\n"
        f"Целевой AI Python файл: {mapping.human_flat_file}\n\n"
        "Ты генерируешь AI-вариант Python-файла для датасета.\n"
        "Нельзя копировать исходник, но нужно сохранить совместимость по смыслу и зависимостям.\n\n"
        "1) Точные импорты, которые нужно учитывать:\n"
        f"{imports_block}\n\n"
        "2) Основные сущности файла (каркас):\n"
        f"Классы:\n{classes_block}\n"
        f"Функции:\n{functions_block}\n\n"
        "3) Псевдокод (что должно быть реализовано):\n"
        f"{steps_block}\n\n"
        "4) Ограничения:\n"
        "- Не вставлять исходные участки кода дословно.\n"
        "- Сохранить назначение файла и общую архитектурную роль.\n"
        "- Допускаются TODO в деталях реализации.\n"
    )


def generate_pseudocode_files(work_root: Path, ai_root: Path, mappings: List[FileMapping]) -> int:
    ai_root.mkdir(parents=True, exist_ok=True)
    created = 0

    for item in mappings:
        src = work_root / item.source_relpath
        source = src.read_text(encoding="utf-8", errors="ignore")
        imports = extract_import_lines(source)
        classes, functions, steps = extract_structure(source)

        txt_target = ai_root / item.ai_txt_file
        txt_target.parent.mkdir(parents=True, exist_ok=True)
        txt_target.write_text(
            build_txt_content(item, imports, classes, functions, steps),
            encoding="utf-8",
        )
        created += 1

    return created


def main() -> int:
    args = parse_args()
    work_root = Path(args.work_root).resolve()
    ai_root = Path(args.ai_root).resolve()
    mapping_file = Path(args.mapping_file).resolve()

    mappings = load_mappings(mapping_file)
    created = generate_pseudocode_files(work_root, ai_root, mappings)
    print(json.dumps({"txt_files_created": created, "ai_root": str(ai_root)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
