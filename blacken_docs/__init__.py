# -*- coding: utf-8 -*-

import importlib
import inspect
import pathlib
import re
import textwrap
import traceback
from types import FunctionType
from typing import List, NamedTuple, Sequence, Set, Tuple

import black
import click

from .formatter import blacken_code_blocks, fix_inline, wrap_text


class CodeBlockError(NamedTuple):
    src: str
    exc: Exception


def format_str(src: str, *, mode: black.FileMode,) -> Tuple[str, Sequence[CodeBlockError]]:
    errors: List[CodeBlockError] = []
    mode.line_length -= 4  # adjust for tabs
    try:
        src = blacken_code_blocks(src, mode=mode)
        src = wrap_text(src, mode=mode)
        src = fix_inline(src)
        src = textwrap.dedent(f" {src}")
    except Exception as exc:
        errors.append(CodeBlockError(src, exc))
    finally:
        return src, errors


def format_py_file(path: pathlib.Path, *, mode: black.Mode, report: black.Report):
    path = path.absolute()
    file = importlib.import_module(path)
    original = open(path).read()

    def format_object(obj: object, indent: int):
        black.reformat_one(
            src=path, fast=False, write_back=black.WriteBack.YES, mode=mode, report=report,
        )
        for _, attr in inspect.getmembers(obj):
            format_object(attr, indent + 4)
        to_format = inspect.getdoc(obj)
        formatted = format_str(to_format, mode=mode)
        current = open(path).read()
        search = re.search(rf'{obj.__name__}.*:\s+"""(.*)"""', current, re.S)
        final = textwrap.indent(textwrap.dedent(formatted), prefix=" " * indent).strip()
        to_write = current.replace(search.group(1), final)
        open(path, "w+").write(to_write)

    for _, attr in inspect.getmembers(file):  # needs to be recursive
        if isinstance(attr, FunctionType):
            format_object(attr, indent=4)
        elif inspect.isclass(attr):
            format_object(attr)

    new = open(path).read()
    open(path, "w+").write(original)
    return new


def format_rst_file(path: pathlib.Path, *, mode: black.Mode):
    original = open(path.absolute()).read()
    return format_str(original, mode=mode)


def format_file(file: pathlib.Path, mode: black.FileMode, report: black.Report,) -> int:
    with open(file, encoding="UTF-8") as f:
        original = f.read()

    if file.name.endswith(".py"):
        new_contents, errors = format_py_file(file, mode=mode, report=report)
    else:
        new_contents, errors = format_rst_file(file, mode=mode)

    for error in errors:
        lineno = original.count(error.src) + 1
        report.failed(file, f"{file}:{lineno}: code block parse error {error.exc}")
    if errors:
        return 1
    if original != new_contents and not report.check:
        print(f"{file}: Rewriting...")
        with open(file, "w", encoding="UTF-8") as f:
            try:
                f.write(new_contents)
            except Exception:
                report.failed(file, traceback.format_exc(limit=1))
            else:
                report.done(file, black.Changed.YES)

    elif original != new_contents and report.check and report.diff:
        report.done(file, black.Changed.YES)
    else:
        report.done(file, black.Changed.NO)


def recursive_file_finder(path: pathlib.Path) -> Set[pathlib.Path]:
    ret = set()
    for f in path.iterdir():
        if not f.name.endswith((".rst", ".py")):
            continue
        if f.is_dir():
            ret.update(recursive_file_finder(f))
        elif f.is_file():
            ret.add(f)
        else:
            black.err(f"invalid path: {f}")
    return ret


@click.command(context_settings=dict(help_option_names=["-h", "--help"]))
@click.option(
    "-l",
    "--line-length",
    type=int,
    default=black.DEFAULT_LINE_LENGTH,
    help="How many characters per line to allow.",
    show_default=True,
)
@click.option(
    "-t",
    "--target-version",
    type=click.Choice([v.name.lower() for v in black.TargetVersion]),
    callback=lambda c, p, v: [black.TargetVersion[val.upper()] for val in v],
    multiple=True,
    help="Python versions that should be supported by Black's output. [default: per-file auto-detection]",
)
@click.option(
    "-S", "--skip-string-normalization", is_flag=True, help="Don't normalize string quotes or prefixes.",
)
@click.option(
    "--check",
    is_flag=True,
    help=(
        "Don't write the files back, just return the status.  Return code 0 means"
        " nothing would change.  Return code 1 means some files would be reformatted."
        " Return code 123 means there was an internal error."
    ),
)
@click.option(
    "--diff", is_flag=True, help="Don't write the files back, just output a diff for each file on stdout.",
)
@click.argument(
    "src",
    nargs=-1,
    type=click.Path(exists=True, file_okay=True, dir_okay=True, readable=True, allow_dash=True),
    is_eager=True,
)
@click.pass_context
def main(
    ctx: click.Context,
    line_length: int,
    target_version: Set[black.TargetVersion],
    check: bool,
    diff: bool,
    skip_string_normalization: bool,
    src: Tuple[str, ...],
) -> None:

    report = black.Report(check=check, diff=diff)
    root = black.find_project_root(src)
    sources = recursive_file_finder(root)

    mode = black.Mode(
        target_versions=target_version, line_length=line_length, string_normalization=not skip_string_normalization,
    )

    for filename in sources:
        format_file(filename, mode, report=report)
    print("Oh no! 💥 💔 💥" if report.return_code else "All done! ✨ 🍰 ✨")
    print(str(report))
    ctx.exit(report.return_code)


def patched_main():
    black.freeze_support()
    black.patch_click()
    main()


if __name__ == "__main__":
    patched_main()
