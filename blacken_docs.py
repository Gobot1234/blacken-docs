# -*- coding: utf-8 -*-
import contextlib
import pathlib
import re
import textwrap
import traceback
from typing import Generator, Set
from typing import List
from typing import Match
from typing import NamedTuple
from typing import Sequence
from typing import Tuple

import black
import click

MD_RE = re.compile(
    r"(?P<before>^(?P<indent> *)```python\n)"
    r"(?P<code>.*?)"
    r"(?P<after>^(?P=indent)```\s*$)",
    re.DOTALL | re.MULTILINE,
)
PY_LANGS = "(python|py|sage|python3|py3|numpy)"
BLOCK_TYPES = "(code|code-block|sourcecode|ipython)"
RST_RE = re.compile(
    rf"(?P<before>"
    rf"^(?P<indent> *)\.\. (jupyter-execute::|{BLOCK_TYPES}:: {PY_LANGS})\n"
    rf"((?P=indent) +:.*\n)*"
    rf"\n*"
    rf")"
    rf"(?P<code>(^((?P=indent) +.*)?\n)+)",
    re.MULTILINE,
)
LATEX_RE = re.compile(
    r"(?P<before>^(?P<indent> *)\\begin{minted}{python}\n)"
    r"(?P<code>.*?)"
    r"(?P<after>^(?P=indent)\\end{minted}\s*$)",
    re.DOTALL | re.MULTILINE,
)
PYTHONTEX_LANG = r"(?P<lang>pyblock|pycode|pyconsole|pyverbatim)"
PYTHONTEX_RE = re.compile(
    rf"(?P<before>^(?P<indent> *)\\begin{{{PYTHONTEX_LANG}}}\n)"
    rf"(?P<code>.*?)"
    rf"(?P<after>^(?P=indent)\\end{{(?P=lang)}}\s*$)",
    re.DOTALL | re.MULTILINE,
)
INDENT_RE = re.compile("^ +(?=[^ ])", re.MULTILINE)
TRAILING_NL_RE = re.compile(r"\n+\Z", re.MULTILINE)


class CodeBlockError(NamedTuple):
    offset: int
    exc: Exception


def format_str(
    src: str, black_mode: black.FileMode,
) -> Tuple[str, Sequence[CodeBlockError]]:
    errors: List[CodeBlockError] = []

    @contextlib.contextmanager
    def _collect_error(match: Match[str]) -> Generator[None, None, None]:
        try:
            yield
        except Exception as e:
            errors.append(CodeBlockError(match.start(), e))

    def _md_match(match: Match[str]) -> str:
        code = textwrap.dedent(match["code"])
        with _collect_error(match):
            code = black.format_str(code, mode=black_mode)
        code = textwrap.indent(code, match["indent"])
        return f'{match["before"]}{code}{match["after"]}'

    def _rst_match(match: Match[str]) -> str:
        min_indent = min(INDENT_RE.findall(match["code"]))
        trailing_ws_match = TRAILING_NL_RE.search(match["code"])
        assert trailing_ws_match
        trailing_ws = trailing_ws_match.group()
        code = textwrap.dedent(match["code"])
        with _collect_error(match):
            code = black.format_str(code, mode=black_mode)
        code = textwrap.indent(code, min_indent)
        return f'{match["before"]}{code.rstrip()}{trailing_ws}'

    def _latex_match(match: Match[str]) -> str:
        code = textwrap.dedent(match["code"])
        with _collect_error(match):
            code = black.format_str(code, mode=black_mode)
        code = textwrap.indent(code, match["indent"])
        return f'{match["before"]}{code}{match["after"]}'

    src = MD_RE.sub(_md_match, src)
    src = RST_RE.sub(_rst_match, src)
    src = LATEX_RE.sub(_latex_match, src)
    src = PYTHONTEX_RE.sub(_latex_match, src)
    return src, errors


def format_file(
    file: pathlib.Path, black_mode: black.FileMode, report: black.Report,
) -> int:
    with open(file, encoding="UTF-8") as f:
        contents = f.read()
    new_contents, errors = format_str(contents, black_mode)
    for error in errors:
        lineno = contents[: error.offset].count("\n") + 1
        report.failed(file, f"{file}:{lineno}: code block parse error {error.exc}")
    if errors:
        return 1
    if contents != new_contents and not report.check:
        print(f"{file}: Rewriting...")
        with open(file, "w", encoding="UTF-8") as f:
            try:
                f.write(new_contents)
            except Exception:
                report.failed(file, traceback.format_exc(limit=1))
            else:
                report.done(file, black.Changed.YES)

    elif contents != new_contents and report.check and report.diff:
        report.done(file, black.Changed.YES)
    else:
        report.done(file, black.Changed.NO)


def recursive_file_finder(path: pathlib.Path) -> Set[pathlib.Path]:
    ret = set()
    for f in path.iterdir():
        if not f.name.endswith((".md", ".rst", ".tex",)):
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
    help=(
        "Python versions that should be supported by Black's output. [default: per-file"
        " auto-detection]"
    ),
)
@click.option(
    "-S",
    "--skip-string-normalization",
    is_flag=True,
    help="Don't normalize string quotes or prefixes.",
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
    "--diff",
    is_flag=True,
    help="Don't write the files back, just output a diff for each file on stdout.",
)
@click.argument(
    "src",
    nargs=-1,
    type=click.Path(
        exists=True, file_okay=True, dir_okay=True, readable=True, allow_dash=True
    ),
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

    black_mode = black.Mode(
        target_versions=target_version,
        line_length=line_length,
        string_normalization=not skip_string_normalization,
    )

    for filename in sources:
        format_file(filename, black_mode, report=report)
    print("Oh no! 💥 💔 💥" if report.return_code else "All done! ✨ 🍰 ✨")
    print(str(report))
    ctx.exit(report.return_code)


if __name__ == "__main__":
    black.freeze_support()
    black.patch_click()
    main()
