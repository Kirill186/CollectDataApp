#!/usr/bin/env python3
"""CLI for building a human/ai Python-code detection dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List
from urllib import error, request


@dataclass
class ProjectPaths:
    dataset_root: Path
    raw_repo_root: Path
    human_root: Path
    ai_root: Path
    human_meta_root: Path
    ai_meta_root: Path
    manifests_dir: Path
    dataset_manifest: Path
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
    raw_repo_root = dataset_root / "raw" / repo_name
    human_root = raw_repo_root / "human"
    ai_root = raw_repo_root / "ai"
    human_meta_root = raw_repo_root / "human_json"
    ai_meta_root = raw_repo_root / "ai_json"
    manifests_dir = dataset_root / "manifests"
    dataset_manifest = manifests_dir / "dataset.jsonl"
    work_dir = dataset_root / "work" / repo_name

    for p in [
        human_root,
        ai_root,
        human_meta_root,
        ai_meta_root,
        manifests_dir,
        work_dir.parent,
    ]:
        p.mkdir(parents=True, exist_ok=True)

    if not dataset_manifest.exists():
        dataset_manifest.touch()

    return ProjectPaths(
        dataset_root=dataset_root,
        raw_repo_root=raw_repo_root,
        human_root=human_root,
        ai_root=ai_root,
        human_meta_root=human_meta_root,
        ai_meta_root=ai_meta_root,
        manifests_dir=manifests_dir,
        dataset_manifest=dataset_manifest,
        work_dir=work_dir,
    )


def clone_and_checkout(repo_url: str, commit: str, target_dir: Path) -> None:
    if target_dir.exists():
        shutil.rmtree(target_dir)
    run_cmd(["git", "clone", repo_url, str(target_dir)])
    run_cmd(["git", "checkout", commit], cwd=target_dir)


def ignore_git(path: str, names: List[str]) -> Iterable[str]:
    ignored = {".git", "__pycache__", ".pytest_cache", ".mypy_cache"}
    return [n for n in names if n in ignored]


def copy_repo_snapshot(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore_git)


def list_python_files(root: Path) -> List[Path]:
    return [p for p in root.rglob("*.py") if p.is_file()]


def extract_library_name(import_line: str) -> str | None:
    import_line = import_line.strip()
    if import_line.startswith("import "):
        chunk = import_line[len("import ") :].split(",")[0].strip()
        return chunk.split(".")[0] if chunk else None
    if import_line.startswith("from "):
        chunk = import_line[len("from ") :].split(" import ")[0].strip()
        return chunk.split(".")[0] if chunk else None
    return None


def build_project_descriptor(py_files: List[Path], root: Path) -> Dict[str, List[str]]:
    structure = sorted(str(p.relative_to(root)).replace("\\", "/") for p in py_files)
    imports_map = collect_imports(py_files, root)

    libs: set[str] = set()
    for imports in imports_map.values():
        for line in imports:
            lib = extract_library_name(line)
            if lib:
                libs.add(lib)

    return {
        "libraries": sorted(libs),
        "python_files": structure,
    }


def write_descriptor_txt(target_file: Path, descriptor: Dict[str, List[str]]) -> None:
    lines: List[str] = []
    lines.append("Project descriptor (no source code)")
    lines.append("")
    lines.append("Libraries:")
    if descriptor["libraries"]:
        lines.extend(f"- {lib}" for lib in descriptor["libraries"])
    else:
        lines.append("- (none detected)")
    lines.append("")
    lines.append("Approximate structure:")
    if descriptor["python_files"]:
        lines.extend(f"- {rel}" for rel in descriptor["python_files"])
    else:
        lines.append("- (no python files found)")
    target_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_file_metadata(meta_root: Path, label: str, repo: str, source_root: Path, files: List[Path]) -> None:
    if meta_root.exists():
        for p in meta_root.glob("*.json"):
            p.unlink()
    meta_root.mkdir(parents=True, exist_ok=True)

    for i, file_path in enumerate(sorted(files), start=1):
        rel = file_path.relative_to(source_root)
        metadata = {
            "id": f"{repo}_{label}_{i:04d}",
            "repo": repo,
            "label": label,
            "source_file": str(rel).replace("\\", "/"),
            "abs_dataset_path": str(file_path),
            "language": "python",
        }
        meta_name = f"{label}_{i:04d}.json"
        (meta_root / meta_name).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def split_for_repo(repo_name: str) -> str:
    buckets = ["train", "val", "test"]
    digest = hashlib.sha256(repo_name.encode("utf-8")).hexdigest()
    return buckets[int(digest[:2], 16) % len(buckets)]


def append_manifest_entries(manifest_path: Path, repo_name: str, label: str, base_root: Path, files: List[Path]) -> int:
    split = split_for_repo(repo_name)
    entries = []
    for i, file_path in enumerate(sorted(files), start=1):
        rel = file_path.relative_to(base_root.parent.parent.parent)
        entries.append(
            {
                "id": f"{repo_name}_{'h' if label == 'human' else 'ai'}_{i:04d}",
                "repo": repo_name,
                "label": label,
                "file_relpath": str(rel).replace("\\", "/"),
                "split": split,
                "lang": "python",
            }
        )

    with manifest_path.open("a", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return len(entries)


def choose_ai_sample_dir(ai_root: Path) -> Path:
    existing = sorted(
        [p for p in ai_root.iterdir() if p.is_dir() and p.name.startswith("sample_")],
        key=lambda p: p.name,
    )
    if not existing:
        return ai_root / "sample_001"
    last = existing[-1].name
    suffix = int(last.split("_")[-1])
    return ai_root / f"sample_{suffix + 1:03d}"


def truncate(text: str, limit: int = 6000) -> str:
    return text if len(text) <= limit else text[:limit] + "\n# ...truncated..."


def make_prompt(repo_name: str, structure: List[str], imports_map: Dict[str, List[str]]) -> str:
    return (
        f"Generate a Python project skeleton similar to repository '{repo_name}'. "
        "It can be non-working, but should look like AI-written code. Return ONLY JSON object with key 'files' "
        "that contains list of objects: {path, content}. Keep file paths relative and Python-only.\n\n"
        f"Existing structure:\n{json.dumps(structure, ensure_ascii=False, indent=2)}\n\n"
        f"Imports detected:\n{json.dumps(imports_map, ensure_ascii=False, indent=2)}"
    )


def collect_imports(py_files: List[Path], root: Path) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    for py_file in py_files:
        imports: List[str] = []
        for line in py_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("import ") or line.startswith("from "):
                imports.append(line)
        if imports:
            result[str(py_file.relative_to(root)).replace("\\", "/")] = imports[:15]
    return result


def generate_ai_project_via_openai(
    api_key: str,
    model: str,
    repo_name: str,
    human_root: Path,
    ai_sample_dir: Path,
) -> None:
    py_files = list_python_files(human_root)
    descriptor = build_project_descriptor(py_files[:300], human_root)

    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": "You are a code generator."},
            {"role": "user", "content": make_prompt(repo_name, descriptor["python_files"][:150], {"libraries": descriptor["libraries"]})},
        ],
        "max_output_tokens": 6000,
    }

    req = request.Request(
        "https://api.openai.com/v1/responses",
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        details = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpenAI API HTTP {e.code}: {details}") from e
    except Exception as e:
        raise RuntimeError(f"Failed to call OpenAI API: {e}") from e

    output_text = ""
    for item in body.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                output_text += content.get("text", "")

    output_text = output_text.strip()
    if output_text.startswith("```"):
        output_text = output_text.strip("`")
        output_text = output_text.replace("json", "", 1).strip()

    try:
        generated = json.loads(output_text)
    except json.JSONDecodeError:
        fallback = ai_sample_dir / "generated_fallback.py"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.write_text(
            "# Fallback synthetic file because model response was not valid JSON\n" + truncate(output_text),
            encoding="utf-8",
        )
        return

    files = generated.get("files", [])
    if not isinstance(files, list):
        raise RuntimeError("Model returned malformed payload: 'files' must be a list")

    for item in files:
        if not isinstance(item, dict):
            continue
        rel_path = item.get("path")
        content = item.get("content", "")
        if not rel_path or not str(rel_path).endswith(".py"):
            continue

        normalized = Path(rel_path)
        if ".." in normalized.parts or normalized.is_absolute():
            continue

        target = ai_sample_dir / normalized
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")


def local_ai_fallback(human_root: Path, ai_sample_dir: Path) -> None:
    py_files = list_python_files(human_root)
    descriptor = build_project_descriptor(py_files, human_root)

    selected_paths = descriptor["python_files"][: min(20, len(descriptor["python_files"]))]
    if not selected_paths:
        fallback_file = ai_sample_dir / "main.py"
        fallback_file.parent.mkdir(parents=True, exist_ok=True)
        fallback_file.write_text(
            '"""Synthetic AI project placeholder."""\n\n'
            "def main() -> None:\n"
            "    print('synthetic project')\n\n"
            "if __name__ == '__main__':\n"
            "    main()\n",
            encoding="utf-8",
        )
        return

    libs = descriptor["libraries"][:10]
    import_lines = "\n".join(f"import {lib}" for lib in libs if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", lib))
    if import_lines:
        import_lines += "\n\n"

    random.shuffle(selected_paths)
    for rel_str in selected_paths:
        dst = ai_sample_dir / rel_str
        dst.parent.mkdir(parents=True, exist_ok=True)
        class_name = "".join(part.capitalize() for part in Path(rel_str).stem.split("_")) or "Module"
        synthetic = (
            '"""AI-generated synthetic skeleton (no copied source code)."""\n\n'
            f"{import_lines}"
            f"class {class_name}:\n"
            "    def run(self) -> dict:\n"
            "        return {'status': 'synthetic', 'note': 'non-functional sample'}\n\n"
            "def build() -> dict:\n"
            "    return {'ok': True}\n"
        )
        dst.write_text(synthetic, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect dataset sample for AI code detection")
    parser.add_argument("repo_url", help="Git repository URL to clone")
    parser.add_argument("commit", help="Commit hash (or tag/branch) to checkout")
    parser.add_argument(
        "--dataset-root",
        default="dataset",
        help="Dataset root directory (default: ./dataset)",
    )
    parser.add_argument(
        "--api-key-env",
        default="CollectData",
        help="Environment variable containing OpenAI API key (default: CollectData)",
    )
    parser.add_argument(
        "--model",
        default="gpt-4.1-mini",
        help="OpenAI model for AI sample generation",
    )
    parser.add_argument(
        "--fail-on-api-error",
        action="store_true",
        help="Stop execution if OpenAI generation fails instead of using local fallback",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    repo_name = sanitize_repo_name(args.repo_url)
    dataset_root = Path(args.dataset_root).resolve()
    paths = ensure_layout(dataset_root, repo_name)

    print(f"[1/6] Cloning {args.repo_url} into {paths.work_dir}")
    clone_and_checkout(args.repo_url, args.commit, paths.work_dir)

    print("[2/6] Copying snapshot to human dataset")
    copy_repo_snapshot(paths.work_dir, paths.human_root)

    human_files = list_python_files(paths.human_root)
    print(f"[3/6] Found {len(human_files)} Python files in human snapshot")
    write_descriptor_txt(paths.human_root / "descriptor.txt", build_project_descriptor(human_files, paths.human_root))
    write_file_metadata(paths.human_meta_root, "human", repo_name, paths.human_root, human_files)
    human_added = append_manifest_entries(paths.dataset_manifest, repo_name, "human", paths.human_root, human_files)

    ai_sample_dir = choose_ai_sample_dir(paths.ai_root)
    ai_sample_dir.mkdir(parents=True, exist_ok=True)

    api_key = os.getenv(args.api_key_env, "").strip()
    print(f"[4/6] Generating AI sample into {ai_sample_dir}")
    if api_key:
        try:
            generate_ai_project_via_openai(api_key, args.model, repo_name, paths.human_root, ai_sample_dir)
        except RuntimeError as api_error:
            if args.fail_on_api_error:
                raise
            print(
                f"OpenAI generation failed ({api_error}). Falling back to local synthetic generation.",
                file=sys.stderr,
            )
            local_ai_fallback(paths.human_root, ai_sample_dir)
    else:
        print(
            f"Environment variable '{args.api_key_env}' is empty. Using local fallback generation.",
            file=sys.stderr,
        )
        local_ai_fallback(paths.human_root, ai_sample_dir)

    ai_files = list_python_files(ai_sample_dir)
    write_descriptor_txt(ai_sample_dir / "descriptor.txt", build_project_descriptor(ai_files, ai_sample_dir))
    print(f"[5/6] Found {len(ai_files)} Python files in generated AI sample")
    write_file_metadata(paths.ai_meta_root, "ai", repo_name, ai_sample_dir, ai_files)
    ai_added = append_manifest_entries(paths.dataset_manifest, repo_name, "ai", ai_sample_dir, ai_files)

    print("[6/6] Done")
    print(
        json.dumps(
            {
                "repo": repo_name,
                "human_files_added": human_added,
                "ai_files_added": ai_added,
                "manifest": str(paths.dataset_manifest),
                "ai_sample": ai_sample_dir.name,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
