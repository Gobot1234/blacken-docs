import builtins
import inspect
import re
import textwrap
from typing import Tuple
import string as _string

import black


PY_LANGS = ("python", "py", "sage", "python3", "py3", "numpy")
BLOCK_TYPES = ("code", "code-block", "sourcecode", "ipython")
EXCEPTIONS = tuple(
    name for name, _ in inspect.getmembers(builtins, lambda e: inspect.isclass(e) and BaseException in e.__mro__)
)
TYPES = tuple(
    name
    for name, _ in inspect.getmembers(
        builtins, lambda o: inspect.isclass(o) and o.__name__ not in EXCEPTIONS and not o.__name__[0].isupper()
    )
)
INLINE_WRAPPED_TYPES = ("\d+", "None", "NoneType", "True", "False") + EXCEPTIONS + TYPES
PUNCTUATION = tuple(_string.punctuation)

RST_RE = re.compile(
    rf"(?P<before>(?:\S|\s)*"
    rf"(?:jupyter-execute::|(?:{'|'.join(BLOCK_TYPES)}|.*))"
    rf"(?:{'::|'.join(PY_LANGS)}::|::\s)"
    rf"(?:[-+=]*))"
    rf"(?P<indent>\s*)(?P<code>(?:\s|\S)*)^"
    rf"(?P<after>(?:.+|\s)*)",
    re.M,
)
_MULTIPLES = [
    "\s{" + str(i) + "}" for i in range(0, 32, 4)
]  # why would you realistically go higher than this in a docstring?
STARTING_LINE_WS = re.compile(rf'^({"|".join(_MULTIPLES)}) (\w)', re.M)


# need to get the rst prolog and use those

def is_not_fully_wrapped(string: str):
    if len(string) > 4:
        return (
                string.startswith("`") and string.endswith("`") and not (
                    string.startswith("``") and string.endswith("``"))
        )

    return False


FIND_NOT_INLINE_TYPES = re.compile(rf"^({'|'.join(INLINE_WRAPPED_TYPES)})[^()]$")
FIND_INLINE_TYPES = re.compile(rf"^``({'|'.join(INLINE_WRAPPED_TYPES)})``$")


def fix_inline(string: str) -> str:
    formatted = []
    for line in string.splitlines(True):
        for word in line.split(" "):
            if FIND_NOT_INLINE_TYPES.match(word):  # general match
                if not FIND_INLINE_TYPES.match(word):  # strict match
                    word = FIND_NOT_INLINE_TYPES.sub(r"``\1``", word.strip("``"))
            if is_not_fully_wrapped(word):  # simple fix
                word = f"``{word.strip('`')}``"
            formatted.append(word)

    return "\n".join(line for line in " ".join(formatted).splitlines())


def wrap_text(string: str, mode: black.Mode):  # take up as little vertical space as possible
    # maximum vertical space = 2
    # maximum space = 1
    # full stops at the end of every sentence if not tabbed.
    # spaces after any pre added punctuation
    ret = {}
    last_line = " "
    string = string.replace("    ", "\u000E")  # for preserving tabs
    string = re.sub(r"^\n{2,}$", "\n\n", string, re.M)  # preserve a max of 2 new lines
    string = re.sub(r"\n{3}", "\u000F", string)
    for idx, line in enumerate(string.splitlines()):
        if "::" in line or line.startswith("\u000E"):
            pass
        elif not last_line and line and not line.endswith(PUNCTUATION):
            line = f"{line[:1].upper().strip()}{line[1:].strip()}."
        elif last_line.endswith(".") and line and not line.endswith("."):  # transfer full stop
            ret[idx - 1] = last_line[:-1]
            line += "."

        last_line = line
        ret[idx] = line

    string = textwrap.fill("\n".join(ret.values()), width=mode.line_length)
    string = string.replace("  ", "\n").replace("\u000E", "\n    ").replace("\u000F", "\n\n\n")
    return STARTING_LINE_WS.sub(r"\1\2", string).strip()


def blacken_code_blocks(string: str, *, mode: black.Mode) -> str:
    search = RST_RE.search(string)
    if search is None:  # nothing to do
        return string

    mode.line_length -= 4

    def code_formatter(string: str) -> Tuple[str, str, str]:
        search = RST_RE.search(string)
        if search is None:
            return string, "", ""
        code = search.group("indent") + search.group("code")
        return (
            search.group("before"),
            textwrap.indent(black.format_str(textwrap.dedent(code), mode=mode), prefix="    "),
            # TODO add support for ">>> " and "... "
            search.group("after"),
        )

    ret = []
    old_before = search.group("before")
    new_before, code, after = code_formatter(string)
    ret.append((new_before, code, after))
    while new_before != old_before:
        new_before, code, after = code_formatter(new_before)
        ret.append((new_before, code, after))
    mode.line_length += 4
    return "".join(f"{i}{j}{k}" for i, j, k in reversed(ret))
