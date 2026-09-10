#!/usr/bin/env python3
"""Офлайн-проверка курса: структура, ссылки, схемы, версия ассетов, запуск лабораторных.

Ничего не качает и никуда не ходит: только файлы репозитория и python3.
PASS означает согласованность материалов, а не педагогическое качество уроков.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOKS = ROOT / "docs/books"
LABS = BOOKS / "labs"

PALETTE = {"#2d2d2d", "#1a5276", "#1e8449", "#6e2f1a", "#7d6608", "#4a235a"}
REQUIRED_SECTIONS = ("## Что мы узнали", "## Проверь себя")

problems = []


def fail(message):
    problems.append(message)


def check_manifest():
    """files.json перечисляет существующие файлы, и наоборот."""
    manifest = json.loads((BOOKS / "files.json").read_text())["courses"]
    listed = set()
    for course, items in manifest.items():
        if Path(course).name != course:
            fail(f"files.json: небезопасное имя темы {course!r}")
            continue
        names = [item["file"] if isinstance(item, dict) else item for item in items]
        if "book.md" not in names or "glossary.md" not in names:
            fail(f"{course}: нужны book.md и glossary.md")
        for name in names:
            path = BOOKS / course / name
            listed.add(path)
            if not path.is_file():
                fail(f"files.json ссылается на несуществующий {course}/{name}")
    on_disk = {p for p in BOOKS.glob("*/*.md")}
    for path in sorted(on_disk - listed):
        fail(f"файл есть на диске, но не указан в files.json: {path.relative_to(BOOKS)}")
    return manifest


def check_chapter(path, course, manifest):
    text = path.read_text()

    if text.count("```") % 2:
        fail(f"{path.name} ({course}): нечётное число ``` — незакрытый блок кода")

    for block in re.findall(r"```mermaid\n(.*?)```", text, re.S):
        if not block.lstrip().startswith("flowchart TD"):
            fail(f"{path.name} ({course}): схема не 'flowchart TD' (правила курса)")
        if block.count('"') % 2:
            fail(f"{path.name} ({course}): нечётное число кавычек в схеме")
        for colour in re.findall(r"fill:(#[0-9a-f]{6})", block):
            if colour not in PALETTE:
                fail(f"{path.name} ({course}): цвет {colour} вне палитры курса")
        for style in re.findall(r"style \w+ fill:#[0-9a-f]{6}[^\n]*", block):
            if "color:#fff" not in style:
                fail(f"{path.name} ({course}): у заливки нет color:#fff — {style.strip()}")

    # Ссылки: код в ``` не проверяем, там встречаются f-строки вида {a}({b}).
    without_code = re.sub(r"```.*?```", "", text, flags=re.S)
    for _, href in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", without_code):
        if href.startswith(("http", "reader.html", "#")):
            continue
        target = (BOOKS / href) if href.startswith("labs/") else (path.parent / href)
        if not target.is_file():
            fail(f"{path.name} ({course}): битая ссылка -> {href}")

    if path.name.startswith("chapter-"):
        if not re.search(r"^> \*\*[^*]+\*\*[^\n—]{0,80}—", text, re.M):
            fail(f"{path.name} ({course}): нет ни одного определения блоком '> **Термин** — ...'")
        for section in REQUIRED_SECTIONS:
            if section not in text:
                fail(f"{path.name} ({course}): нет раздела {section!r}")
        if "```mermaid" not in text:
            fail(f"{path.name} ({course}): в уроке нет ни одной схемы")


def check_asset_version():
    """Три места должны называть одну версию, иначе браузер отдаст старое из кэша."""
    index = (BOOKS / "index.html").read_text()
    reader = (BOOKS / "reader.html").read_text()
    versions = {
        "index.html": re.search(r"ASSET_VERSION = '([^']+)'", index).group(1),
        "reader.html": re.search(r"ASSET_VERSION = '([^']+)'", reader).group(1),
        "reader-links.js?v=": re.search(r"reader-links\.js\?v=([^\"']+)", reader).group(1),
    }
    if len(set(versions.values())) != 1:
        fail(f"ASSET_VERSION расходится: {versions}")


def check_reader_registration(manifest):
    """Каждая тема должна быть подписана в каталоге и в читалке."""
    index = (BOOKS / "index.html").read_text()
    reader = (BOOKS / "reader.html").read_text()
    for course in manifest:
        if f'"{course}"' not in index:
            fail(f"{course}: нет записи в COURSE_META (index.html)")
        if f'"{course}"' not in reader:
            fail(f"{course}: нет записи в COURSE_NAMES (reader.html)")


def check_labs():
    """Каждая лабораторная запускается и её код совпадает с кодом в уроке."""
    lab_files = sorted(LABS.glob("*/*.py"))
    if not lab_files:
        fail("лабораторных не найдено")

    chapters = {p: p.read_text() for p in BOOKS.glob("*/chapter-*.md")}

    for lab in lab_files:
        relative = lab.relative_to(BOOKS).as_posix()
        result = subprocess.run(
            [sys.executable, lab.name], cwd=lab.parent,
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            fail(f"{relative}: падает при запуске\n{result.stderr.strip()[:500]}")

        body = lab.read_text().strip()
        mentioned = [text for text in chapters.values() if relative in text]
        if not mentioned:
            fail(f"{relative}: на файл не ссылается ни один урок")
            continue
        # Код в уроке дублирует файл: расходиться они не должны.
        first_line = f"# {relative}"
        for text in mentioned:
            for block in re.findall(r"```python\n(.*?)```", text, re.S):
                if block.startswith(first_line):
                    in_lesson = block.split("\n", 1)[1].strip()
                    if in_lesson != body:
                        fail(f"{relative}: код в уроке разошёлся с файлом")
                    break


def main():
    manifest = check_manifest()
    for course, items in manifest.items():
        for item in items:
            name = item["file"] if isinstance(item, dict) else item
            path = BOOKS / course / name
            if path.is_file():
                check_chapter(path, course, manifest)
    check_asset_version()
    check_reader_registration(manifest)
    check_labs()

    chapters = len(list(BOOKS.glob("*/chapter-*.md")))
    diagrams = sum(p.read_text().count("```mermaid") for p in BOOKS.glob("*/*.md"))
    labs = len(list(LABS.glob("*/*.py")))

    if problems:
        print(f"FAIL: {len(problems)} проблем(ы)")
        for problem in problems:
            print(" -", problem)
        return 1

    print(f"PASS: тем {len(manifest)}, уроков {chapters}, схем {diagrams}, лабораторных {labs}")
    print("Проверены: структура, ссылки, палитра схем, версия ассетов, запуск лабораторных.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
