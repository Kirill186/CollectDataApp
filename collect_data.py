#!/usr/bin/env python3
"""CLI for preparing a manual human/ai Python dataset from repository snapshots."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from generate_pseudocode_txt import FileMapping, generate_pseudocode_files


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

    return ProjectPaths(dataset_root=dataset_root, human_root=human_root, ai_root=ai_root, work_dir=work_dir)


def clone_and_checkout(repo_url: str, commit: str, target_dir: Path) -> None:
    if target_dir.exists():
        shutil.rmtree(target_dir)
    run_cmd(["git", "clone", repo_url, str(target_dir)])
    run_cmd(["git", "checkout", commit], cwd=target_dir)


def list_python_files(root: Path) -> List[Path]:
    return sorted([p for p in root.rglob("*.py") if p.is_file() and ".git" not in p.parts])


def flatten_name(rel_path: Path, used_names: Dict[str, int]) -> str:
    stem = "__".join(rel_path.with_suffix("").parts)
    candidate = f"{stem}.py"
    counter = used_names.get(candidate, 0)
    if counter == 0:
        used_names[candidate] = 1
        return candidate

    while True:
        counter += 1
        with_suffix = f"{stem}__dup{counter}.py"
        if with_suffix not in used_names:
            used_names[candidate] = counter
            used_names[with_suffix] = 1
            return with_suffix


def copy_python_files_flat(src_root: Path, dst_root: Path) -> List[FileMapping]:
    if dst_root.exists():
        shutil.rmtree(dst_root)
    dst_root.mkdir(parents=True, exist_ok=True)

    used_names: Dict[str, int] = {}
    mappings: List[FileMapping] = []

    for py_file in list_python_files(src_root):
        rel = py_file.relative_to(src_root)
        flat_name = flatten_name(rel, used_names)

        target = dst_root / flat_name
        shutil.copy2(py_file, target)

        mappings.append(
            FileMapping(
                source_relpath=str(rel).replace("\\", "/"),
                human_flat_file=flat_name,
                ai_txt_file=Path(flat_name).with_suffix(".txt").name,
            )
        )

    return mappings


def build_manual_ai_prompt(repo_name: str, mappings: List[FileMapping]) -> str:
    flat_files = [m.human_flat_file for m in mappings]
    return (
        "Ты участвуешь в генерации датасета для детекции AI-vs-human Python кода.\n"
        f"Репозиторий: {repo_name}.\n"
        "Тебе даны txt-файлы с псевдокодом и точными импортами для каждого python-файла.\n"
        "Каждый txt соответствует одному целевому .py файлу.\n\n"
        "Правила:\n"
        "- Не копируй исходный код дословно.\n"
        "- Соблюдай импорты и общую структуру из txt.\n"
        "- Генерируй рабочий черновик в стиле AI, сохраняя роль файла.\n\n"
        "Список flattened файлов в human:\n"
        f"{json.dumps(flat_files, ensure_ascii=False, indent=2)}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare manual AI/human dataset from repository")
    parser.add_argument("repo_url", help="Git repository URL to clone")
    parser.add_argument("commit", help="Commit hash (or tag/branch) to checkout")
    parser.add_argument("--dataset-root", default="dataset", help="Dataset root directory (default: ./dataset)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    repo_name = sanitize_repo_name(args.repo_url)
    dataset_root = Path(args.dataset_root).resolve()
    paths = ensure_layout(dataset_root, repo_name)

    print(f"[1/5] Cloning {args.repo_url} into {paths.work_dir}")
    clone_and_checkout(args.repo_url, args.commit, paths.work_dir)

    print("[2/5] Copying all .py into one folder (flattened) for raw/human")
    mappings = copy_python_files_flat(paths.work_dir, paths.human_root)

    print("[3/5] Generating pseudocode txt files in raw/ai")
    if paths.ai_root.exists():
        shutil.rmtree(paths.ai_root)
    paths.ai_root.mkdir(parents=True, exist_ok=True)
    txt_created = generate_pseudocode_files(paths.work_dir, paths.ai_root, mappings)

    mapping_file = paths.ai_root / "mapping.json"
    mapping_file.write_text(
        json.dumps([m.__dict__ for m in mappings], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("[4/5] Building global prompt")
    prompt = build_manual_ai_prompt(repo_name, mappings)
    prompt_file = paths.ai_root / "PROMPT.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    print("[5/5] Done")
    print(
        json.dumps(
            {
                "repo": repo_name,
                "human_py_files": len(mappings),
                "ai_txt_files": txt_created,
                "human_root": str(paths.human_root),
                "ai_root": str(paths.ai_root),
                "prompt_file": str(prompt_file),
                "mapping_file": str(mapping_file),
                "next_step": f"python3 txt_to_py.py --ai-root {paths.ai_root}",
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
