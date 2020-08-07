# -*- coding: utf-8 -*-

import builtins
import inspect
import re
import textwrap
import string as _string

import black
from docutils import nodes, utils
from docutils.core import Publisher

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
_MULTIPLES = [
    "\s{" + str(i) + "}" for i in range(0, 32, 4)
]  # why would you realistically go higher than this in a docstring?
STARTING_LINE_WS = re.compile(rf'^({"|".join(_MULTIPLES)}) (\w)', re.M)
POSSIBLE_TITLES = (
    "Args",
    "Arguments",
    "Attention",
    "Attributes",
    "Caution",
    "Danger",
    "Error",
    "Example",
    "Examples",
    "Hint",
    "Important",
    "Keyword Args",
    "Keyword Arguments",
    "Methods",
    "Note",
    "Notes",
    "Other Parameters",
    "Parameters",
    "Return",
    "Returns",
    "Raise",
    "Raises",
    "References",
    "See Also",
    "Tip",
    "Todo",
    "Warning",
    "Warnings",
    "Warn",
    "Warns",
    "Yield",
    "Yields",
)


# need to get the rst prolog and use those


def is_not_fully_wrapped(string: str):
    if len(string) > 4:
        return (
            string.startswith("`") and string.endswith("`") and not (string.startswith("``") and string.endswith("``"))
        )

    return False


FIND_NOT_INLINE_TYPES = re.compile(rf"^({'|'.join(INLINE_WRAPPED_TYPES)})\W?$")
FIND_INLINE_TYPES = re.compile(rf"^``({'|'.join(INLINE_WRAPPED_TYPES)})``\W?$")


def fix_inline(string: str) -> str:
    formatted = []
    for line in string.splitlines(True):
        for word in line.split(" "):
            if FIND_NOT_INLINE_TYPES.match(word):  # general match
                if not FIND_INLINE_TYPES.match(word):  # strict match
                    word = FIND_NOT_INLINE_TYPES.sub(r"``\1``", word.strip("`"))
            if is_not_fully_wrapped(word):  # simple fix
                word = f"``{word.strip('`')}``"
            formatted.append(word)

    text = "\n".join(" ".join(formatted).splitlines())
    return textwrap.dedent(f" {text}")  # don't why ask


def wrap_text(string: str, mode: black.Mode):  # take up as little vertical space as possible
    # maximum vertical space = 2
    # maximum space = 1
    # full stops at the end of every sentence if not tabbed.
    # spaces after any pre added punctuation
    """ret = {}
    last_line = " "
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

    """
    # FIXME
    return textwrap.fill(string, width=mode.line_length)
    string = textwrap.fill(string, width=mode.line_length)
    string = string.replace("  ", "\n").replace("\u000F", "\n\n\n")
    return STARTING_LINE_WS.sub(r"\1\2", string)


def blacken_code_blocks(code: str, *, mode: black.Mode, indent=4) -> str:
    return textwrap.indent(black.format_str(textwrap.dedent(code), mode=mode), prefix=" " * indent)
    # TODO add support for ">>> " and "... "


def generate_doc(content: str) -> nodes.document:  # restructuredtext_lint.lint
    """Return a nodes.document ready for reading from."""
    pub = Publisher(None, None, None, settings=None)
    pub.set_components("standalone", "restructuredtext", "pseudoxml")
    settings = pub.get_settings(halt_level=5)
    pub.set_io()
    reader = pub.reader
    document = utils.new_document(None, settings)
    document.reporter.stream = None
    reader.parser.parse(content, document)
    return document


def wrap_and_fix(text: str, *, mode: black.Mode, indent: int = None) -> str:
    if indent is not None:
        mode.line_length -= indent
    text = fix_inline(text)
    text = wrap_text(text, mode=mode)

    if indent is not None:
        mode.line_length += indent
        return textwrap.indent(text, prefix=" " * indent)
    return text
