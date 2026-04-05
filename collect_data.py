#!/usr/bin/env python3
"""CLI for preparing a manual human/ai Python dataset from repository snapshots."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import List


@dataclass
class ProjectPaths:
    dataset_root: Path
    human_root: Path
    ai_root: Path
    work_dir: Path


def run_cmd(args: List[str], cwd: Path | None = None) -> None:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(args)}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )


def sanitize_repo_name(repo_url: str) -> str:
    name = repo_url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)


def ensure_layout(dataset_root: Path, repo_name: str) -> ProjectPaths:
    human_root = dataset_root / "raw" / "human" / repo_name
    ai_root = dataset_root / "raw" / "ai" / repo_name
    work_dir = dataset_root / "work" / repo_name

    for p in [human_root, ai_root, work_dir.parent]:
        p.mkdir(parents=True, exist_ok=True)

    return ProjectPaths(
        dataset_root=dataset_root,
        human_root=human_root,
        ai_root=ai_root,
        work_dir=work_dir,
    )


def clone_and_checkout(repo_url: str, commit: str, target_dir: Path) -> None:
    if target_dir.exists():
        shutil.rmtree(target_dir)
    run_cmd(["git", "clone", repo_url, str(target_dir)])
    run_cmd(["git", "checkout", commit], cwd=target_dir)


def list_python_files(root: Path) -> List[Path]:
    return sorted([p for p in root.rglob("*.py") if p.is_file() and ".git" not in p.parts])


def copy_python_only_snapshot(src_root: Path, dst_root: Path) -> List[Path]:
    if dst_root.exists():
        shutil.rmtree(dst_root)
    dst_root.mkdir(parents=True, exist_ok=True)

    copied: List[Path] = []
    for py_file in list_python_files(src_root):
        rel = py_file.relative_to(src_root)
        target = dst_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(py_file, target)
        copied.append(rel)
    return copied


def extract_imports(py_file: Path) -> List[str]:
    imports: List[str] = []
    for line in py_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("import ") or line.startswith("from "):
            imports.append(line)
    return imports[:12]


def create_ai_text_placeholders(work_root: Path, ai_root: Path, rel_py_files: List[Path]) -> List[Path]:
    if ai_root.exists():
        shutil.rmtree(ai_root)
    ai_root.mkdir(parents=True, exist_ok=True)

    created: List[Path] = []
    for rel_py in rel_py_files:
        src = work_root / rel_py
        imports = extract_imports(src)
        rel_txt = rel_py.with_suffix(".txt")
        dst = ai_root / rel_txt
        dst.parent.mkdir(parents=True, exist_ok=True)

        message = {
            "target_python_file": str(rel_py).replace("\\", "/"),
            "libraries_or_imports_to_consider": imports,
            "task": (
                "Опиши и затем сгенерируй Python-код для этого файла в стиле AI. "
                "Сохрани назначение файла и общий смысл проекта, но без копирования один-в-один."
            ),
            "output_expectation": (
                "На выходе ожидается рабочий черновик Python-файла, "
                "логично встроенный в структуру проекта."
            ),
            "constraints": [
                "Не используй точные фрагменты из оригинала.",
                "Соблюдай совместимость по путям/модулям внутри проекта.",
                "Можно оставлять TODO для бизнес-логики."
            ],
        }
        dst.write_text(json.dumps(message, ensure_ascii=False, indent=2), encoding="utf-8")
        created.append(rel_txt)

    return created


def build_manual_ai_prompt(repo_name: str, rel_py_files: List[Path]) -> str:
    structure = [str(p).replace("\\", "/") for p in rel_py_files]
    return (
        "Ты участвуешь в генерации датасета для детекции AI-vs-human Python кода.\n"
        f"Репозиторий: {repo_name}.\n"
        "Тебе будут даны:\n"
        "1) структура проекта и назначение проекта;\n"
        "2) файлы-подсказки .txt вместо .py в raw/ai/<project>.\n\n"
        "Правила твоей работы:\n"
        "- Для каждого .txt создай соответствующий .py файл с тем же именем (только расширение .py).\n"
        "- Используй библиотеки/импорты и направление, указанные в .txt.\n"
        "- Генерируй реалистичный, но не дословно скопированный код.\n"
        "- Код должен примерно соответствовать ожидаемому результату без избыточной конкретики.\n"
        "- Сохраняй структуру каталогов и модулей проекта.\n\n"
        "Python-структура исходного проекта:\n"
        f"{json.dumps(structure, ensure_ascii=False, indent=2)}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare manual AI/human dataset from repository")
    parser.add_argument("repo_url", help="Git repository URL to clone")
    parser.add_argument("commit", help="Commit hash (or tag/branch) to checkout")
    parser.add_argument(
        "--dataset-root",
        default="dataset",
        help="Dataset root directory (default: ./dataset)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    repo_name = sanitize_repo_name(args.repo_url)
    dataset_root = Path(args.dataset_root).resolve()
    paths = ensure_layout(dataset_root, repo_name)

    print(f"[1/5] Cloning {args.repo_url} into {paths.work_dir}")
    clone_and_checkout(args.repo_url, args.commit, paths.work_dir)

    print("[2/5] Copying only .py files to raw/human")
    rel_py_files = copy_python_only_snapshot(paths.work_dir, paths.human_root)

    print("[3/5] Creating mirrored .txt placeholders in raw/ai")
    ai_txt_files = create_ai_text_placeholders(paths.work_dir, paths.ai_root, rel_py_files)

    print("[4/5] Building prompt for manual AI generation")
    prompt = build_manual_ai_prompt(repo_name, rel_py_files)

    prompt_file = paths.ai_root / "PROMPT.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    print("[5/5] Done")
    print(
        json.dumps(
            {
                "repo": repo_name,
                "human_py_files": len(rel_py_files),
                "ai_txt_files": len(ai_txt_files),
                "human_root": str(paths.human_root),
                "ai_root": str(paths.ai_root),
                "prompt_file": str(prompt_file),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    print("\n=== PROMPT FOR AI ===\n")
    print(prompt)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
