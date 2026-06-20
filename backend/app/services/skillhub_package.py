from __future__ import annotations

import asyncio
import json
import shutil
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from app.schemas.skill import SkillCreate
from app.services.skill_md_parser import FRONTMATTER_RE, _display_name, _parse_frontmatter_lines, _strip_sections

ALLOWED_EXTENSIONS = {
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".js",
    ".cjs",
    ".mjs",
    ".ts",
    ".py",
    ".sh",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".webp",
    ".csv",
    ".html",
}
SCRIPT_EXTENSIONS = {".py", ".sh", ".js", ".cjs", ".mjs", ".ts"}
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PACKAGE_FILES = 500


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_join(root: Path, rel: str) -> Path:
    rel_path = Path(rel.replace("\\", "/"))
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise ValueError(f"非法路径: {rel}")
    target = (root / rel_path).resolve()
    root_resolved = root.resolve()
    if not str(target).startswith(str(root_resolved)):
        raise ValueError(f"路径越界: {rel}")
    return target


def list_package_files(package_dir: Path) -> list[str]:
    if not package_dir.is_dir():
        return []
    files: list[str] = []
    for path in package_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(package_dir).as_posix()
        if rel.startswith(".skillhub/"):
            continue
        files.append(rel)
    return sorted(files)


def has_scripts_dir(package_dir: Path) -> bool:
    scripts = package_dir / "scripts"
    if not scripts.is_dir():
        return False
    return any(p.is_file() and p.suffix in SCRIPT_EXTENSIONS for p in scripts.iterdir())


def read_package_file(package_dir: Path, rel_path: str, *, max_bytes: int = MAX_FILE_BYTES) -> dict:
    target = safe_join(package_dir, rel_path)
    if not target.is_file():
        return {"error": f"文件不存在: {rel_path}"}
    if target.suffix.lower() not in ALLOWED_EXTENSIONS and target.name != "SKILL.md":
        return {"error": f"不支持的文件类型: {rel_path}"}
    size = target.stat().st_size
    if size > max_bytes:
        return {"error": f"文件过大（>{max_bytes} 字节）: {rel_path}"}
    if target.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        return {
            "path": rel_path,
            "binary": True,
            "size": size,
            "message": "二进制资源文件，请通过脚本处理或描述其用途",
        }
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"error": f"无法以 UTF-8 读取: {rel_path}"}
    return {"path": rel_path, "content": content, "size": size}


def parse_skill_md_from_package(package_dir: Path) -> SkillCreate:
    skill_md = package_dir / "SKILL.md"
    if not skill_md.is_file():
        raise ValueError("技能包缺少 SKILL.md")
    content = skill_md.read_text(encoding="utf-8")
    text = content.strip()
    meta: dict[str, str] = {}
    body = text
    match = FRONTMATTER_RE.match(text)
    if match:
        meta = _parse_frontmatter_lines(match.group(1))
        body = match.group(2)

    skill_id = (meta.get("name") or meta.get("id") or package_dir.name).strip().lower()
    description = (meta.get("description") or "").strip()
    if not description:
        raise ValueError("SKILL.md 缺少 description")

    skill_type = meta.get("type", "instruction")
    if skill_type not in {"instruction", "actions", "builtin"}:
        skill_type = "instruction"

    instruction_body = _strip_sections(body)
    display = _display_name(body, skill_id)
    title_override = meta.get("title", "").strip()
    name = title_override or display

    manual_raw = meta.get("disable-model-invocation", meta.get("disable_model_invocation", "false")).lower()
    disable_model_invocation = manual_raw in {"true", "1", "yes"}

    scripts_note = ""
    if has_scripts_dir(package_dir):
        script_names = [
            p.name
            for p in (package_dir / "scripts").iterdir()
            if p.is_file() and p.suffix in SCRIPT_EXTENSIONS
        ]
        if script_names:
            scripts_note = (
                "\n\n## 包内脚本\n"
                "以下脚本可通过 run_skill_script 执行（path 相对于 scripts/）：\n"
                + "\n".join(f"- {n}" for n in sorted(script_names))
            )
    refs = package_dir / "references"
    if refs.is_dir():
        ref_files = [p.name for p in refs.iterdir() if p.is_file()][:20]
        if ref_files:
            scripts_note += (
                "\n\n## 参考资料\n"
                "可通过 read_skill_resource 读取（path 如 references/foo.md）：\n"
                + "\n".join(f"- references/{n}" for n in sorted(ref_files))
            )

    full_content = (instruction_body + scripts_note).strip()

    return SkillCreate(
        id=skill_id,
        name=name,
        description=description,
        type=skill_type,  # type: ignore[arg-type]
        enabled=True,
        disable_model_invocation=disable_model_invocation,
        parameters=[],
        content=full_content,
        actions=[],
        builtin_handler=None,
        source="skillhub",
        package_path=str(package_dir),
        hub_namespace=None,
        hub_version=None,
        has_scripts=has_scripts_dir(package_dir),
    )


def extract_zip_to_dir(zip_bytes: bytes, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    if target_dir.exists() and any(target_dir.iterdir()):
        shutil.rmtree(target_dir)

    file_count = 0
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n and not n.endswith("/")]
        if not names:
            raise ValueError("技能包 zip 为空")

        # Detect single top-level folder wrapper
        top_levels = {n.split("/")[0] for n in names if "/" in n}
        root_prefix = ""
        if len(top_levels) == 1 and all("/" in n for n in names):
            only = next(iter(top_levels))
            if names[0].startswith(f"{only}/"):
                root_prefix = f"{only}/"

        skill_md_rel: str | None = None
        for name in names:
            rel = name[len(root_prefix) :] if root_prefix and name.startswith(root_prefix) else name
            if rel == "SKILL.md" or rel.endswith("/SKILL.md"):
                skill_md_rel = rel
                break
        if not skill_md_rel:
            raise ValueError("技能包缺少 SKILL.md")

        for name in names:
            rel = name[len(root_prefix) :] if root_prefix and name.startswith(root_prefix) else name
            if not rel or rel.endswith("/"):
                continue
            file_count += 1
            if file_count > MAX_PACKAGE_FILES:
                raise ValueError(f"技能包文件数超过限制 ({MAX_PACKAGE_FILES})")
            suffix = Path(rel).suffix.lower()
            if suffix and suffix not in ALLOWED_EXTENSIONS and rel != "SKILL.md":
                continue
            info = zf.getinfo(name)
            if info.file_size > MAX_FILE_BYTES:
                raise ValueError(f"文件过大: {rel}")
            dest = safe_join(target_dir, rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(name))

    return target_dir


def write_metadata(
    package_dir: Path,
    *,
    registry: str,
    namespace: str,
    slug: str,
    version: str,
    fingerprint: str | None = None,
) -> None:
    meta_dir = package_dir / ".skillhub"
    meta_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "skillhub",
        "sourceType": "registry",
        "registryUrl": registry,
        "namespace": namespace,
        "skillSlug": slug,
        "version": version,
        "installedAt": _utc_now_iso(),
        "fingerprint": fingerprint,
    }
    (meta_dir / "metadata.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def run_package_script(
    package_dir: Path,
    script_path: str,
    args: list[str] | None = None,
    *,
    timeout_seconds: int = 60,
    extra_env: dict[str, str] | None = None,
) -> dict:
    rel = script_path.strip().lstrip("/")
    if not rel.startswith("scripts/"):
        rel = f"scripts/{rel}"
    target = safe_join(package_dir, rel)
    if not target.is_file():
        return {"error": f"脚本不存在: {script_path}"}
    if target.suffix.lower() not in SCRIPT_EXTENSIONS:
        return {"error": f"不支持的脚本类型: {target.suffix}"}

    cmd: list[str]
    if target.suffix == ".py":
        cmd = ["python3", str(target)]
    elif target.suffix == ".sh":
        cmd = ["bash", str(target)]
    elif target.suffix in {".js", ".cjs", ".mjs"}:
        cmd = ["node", str(target)]
    elif target.suffix == ".ts":
        cmd = ["npx", "tsx", str(target)]
    else:
        return {"error": f"无法执行: {target.suffix}"}
    if args:
        cmd.extend(str(a) for a in args)

    env = {**dict(**(extra_env or {})), "SKILL_ROOT": str(package_dir.resolve())}
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(package_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**__import__("os").environ, **env},
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        return {"error": f"脚本执行超时（>{timeout_seconds}s）", "script": rel}
    return {
        "script": rel,
        "exit_code": proc.returncode,
        "stdout": stdout.decode("utf-8", errors="replace")[:50000],
        "stderr": stderr.decode("utf-8", errors="replace")[:10000],
    }
