# -*- coding: utf-8 -*-
import argparse
import contextlib
import pathlib
import re
import textwrap
import traceback
from typing import Generator
from typing import List
from typing import Match
from typing import NamedTuple
from typing import Optional
from typing import Sequence
from typing import Tuple

import black


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
    file: pathlib.Path,
    black_mode: black.FileMode,
    skip_errors: bool,
    report: black.Report,
) -> int:
    with open(file, encoding="UTF-8") as f:
        contents = f.read()
    new_contents, errors = format_str(contents, black_mode)
    for error in errors:
        lineno = contents[: error.offset].count("\n") + 1
        report.failed(file, f"{file}:{lineno}: code block parse error {error.exc}")
    if errors and not skip_errors:
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-l", "--line-length", type=int, default=black.DEFAULT_LINE_LENGTH,
    )
    parser.add_argument(
        "-t",
        "--target-version",
        action="append",
        type=lambda v: black.TargetVersion[v.upper()],
        default=[],
        help=f"choices: {[v.name.lower() for v in black.TargetVersion]}",
        dest="target_versions",
    )
    parser.add_argument(
        "-S", "--skip-string-normalization", action="store_true",
    )
    parser.add_argument("-E", "--skip-errors", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--diff", action="store_true")
    parser.add_argument("filenames", nargs="*", default=".")
    args = parser.parse_args(argv)
    copy = tuple(args.filenames)
    args.filenames = []

    for file in copy:
        if file == ".":
            args.filenames = [
                p for p in pathlib.Path(__file__).parent.glob("**/*") if p.is_file()
            ]
        else:
            ret = pathlib.Path(__file__).parent.joinpath(pathlib.Path(file))
            if ret.is_dir():
                args.filenames.extend(p for p in ret.glob("**/*") if p.is_file())
            else:
                args.filenames.append(ret)

    black_mode = black.FileMode(
        target_versions=args.target_versions,
        line_length=args.line_length,
        string_normalization=not args.skip_string_normalization,
    )
    report = black.Report(check=args.check)
    report.diff = args.diff

    for filename in args.filenames:
        format_file(filename, black_mode, skip_errors=args.skip_errors, report=report)
    print("Oh no! 💥 💔 💥" if report.return_code else "All done! ✨ 🍰 ✨")
    print(str(report))
    return report.return_code


if __name__ == "__main__":
    exit(main())
