"""Random multi-module repos for the T1 finder/codemod, with their ground truth.

A *spec* is plain JSON (so a failing one can be saved as a fixture and
replayed); :func:`render` turns it into files. Every true call site sits on a
line tagged ``# S`` and every decoy call on a line tagged ``# D``, so the
finder's answer can be checked line by line, and :func:`expected_source` gives
the exact text the codemod should produce at each site.
"""

from __future__ import annotations

import builtins
import keyword
from typing import Any

from hypothesis import strategies as st

#: style -> (binding form, import line template). ``{n}`` is the bound name.
STYLES: dict[str, tuple[str, str]] = {
    "from": ("class", "from datetime import datetime"),
    "from_alias": ("class", "from datetime import datetime as {n}"),
    "from_multi": ("class", "from datetime import date, datetime, timedelta"),
    "from_paren": ("class", "from datetime import (\n    date,\n    datetime,\n)"),
    "mod": ("module", "import datetime"),
    "mod_alias": ("module", "import datetime as {n}"),
    "reexport_from": ("class", "from pkg.compat import datetime"),
    "reexport_rel": ("class", "from .compat import datetime"),
    "reexport_modmod": ("module", "from pkg.compat2 import datetime"),
    # `compat.datetime.utcnow()`: a class reached through an in-repo module.
    "reexport_attr": ("class_via_module", "from pkg import compat"),
}
#: Styles whose bound name is fixed (and so collide with each other).
FIXED_NAME = {
    "from": "datetime",
    "from_multi": "datetime",
    "from_paren": "datetime",
    "mod": "datetime",
    "reexport_from": "datetime",
    "reexport_rel": "datetime",
    "reexport_modmod": "datetime",
    "reexport_attr": "compat",
}
CORE_STYLES = (
    "from",
    "from_alias",
    "from_multi",
    "from_paren",
    "mod",
    "mod_alias",
    "reexport_from",
    "reexport_rel",
    "reexport_modmod",
)

SITE_CONTEXTS = (
    "module",
    "function",
    "default_arg",
    "lambda",
    "fstring",
    "fstring_conv",
    "decorator",
    "class_body",
    "comprehension",
    "method",
    "nested",
    "kwarg",
    "chained",
    "ternary",
)
DECOYS = (
    "clock",
    "namespace_attr",
    "string",
    "comment",
    "docstring",
    "shadow_local",
    "shadow_param",
    "bare_reference",
    "lambda_param",
    "comprehension_var",
    "class_body_shadow",
)

TRICKY = [
    "dt",
    "DT",
    "Datetime",
    "datetime_",
    "_d",
    "tz",
    "clock",
    "utc",
    "now",
    "date",
    "time",
    "D",
    "x",
]
RESERVED = {"datetime", "compat", "compat2", "pkg", "timezone", "self", "x"}


def _ok_name(name: str) -> bool:
    return (
        name.isidentifier()
        and not keyword.iskeyword(name)
        and not keyword.issoftkeyword(name)
        and name not in dir(builtins)
        and name not in RESERVED
        and not name.startswith("h_")
    )


aliases = st.one_of(
    st.sampled_from(TRICKY), st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,7}", fullmatch=True)
).filter(_ok_name)


@st.composite
def module_specs(draw: Any, styles: tuple[str, ...], extra_aliases: tuple[str, ...] = ()) -> dict:
    count = draw(st.integers(1, min(2, len(styles))))
    chosen: list[dict[str, str]] = []
    used: set[str] = set()
    for style in draw(
        st.lists(st.sampled_from(styles), min_size=count, max_size=count, unique=True)
    ):
        name = FIXED_NAME.get(style)
        if name is None:
            pool = st.one_of(aliases, st.sampled_from(extra_aliases)) if extra_aliases else aliases
            name = draw(pool.filter(lambda n, taken=frozenset(used): n not in taken))
        also = {"from_multi": {"date", "timedelta"}, "from_paren": {"date"}}.get(style, set())
        if name in used or also & used:
            continue
        used |= {name, *also}
        chosen.append({"style": style, "name": name})
    items = []
    for _ in range(draw(st.integers(1, 8))):
        binding = draw(st.integers(0, len(chosen) - 1))
        if draw(st.booleans()):
            items.append(
                {
                    "kind": "site",
                    "ctx": draw(st.sampled_from(SITE_CONTEXTS)),
                    "binding": binding,
                    "method": draw(st.sampled_from(["utcnow", "utcfromtimestamp"])),
                }
            )
        else:
            items.append(
                {
                    "kind": "decoy",
                    "ctx": draw(st.sampled_from(DECOYS)),
                    "binding": binding,
                    "method": "utcnow",
                }
            )
    # `from datetime import timezone` beside an alias named timezone would rebind it.
    has_tz = draw(st.booleans()) and "timezone" not in used
    return {"bindings": chosen, "has_tz": has_tz, "items": items}


@st.composite
def repo_specs(
    draw: Any, styles: tuple[str, ...] = CORE_STYLES, extra_aliases: tuple[str, ...] = ()
) -> dict:
    n = draw(st.integers(1, 4))
    return {"modules": [draw(module_specs(styles, extra_aliases)) for _ in range(n)]}


# -- rendering ---------------------------------------------------------------


def site_text(binding: dict[str, str], method: str) -> tuple[str, str]:
    """(old call text, the exact text the codemod should write)."""
    form = STYLES[binding["style"]][0]
    name = binding["name"]
    arg = "" if method == "utcnow" else "0"
    new_method = "now" if method == "utcnow" else "fromtimestamp"
    if form == "class":
        receiver, tz = name, "timezone.utc"
    elif form == "module":
        receiver, tz = f"{name}.datetime", f"{name}.timezone.utc"
    else:  # class_via_module: the class is reached through compat, timezone is imported
        receiver, tz = f"{name}.datetime", "timezone.utc"
    old = f"{receiver}.{method}({arg})"
    new = f"{receiver}.{new_method}({arg + ', ' if arg else ''}{tz})"
    return old, new


def needs_timezone_import(module: dict) -> bool:
    """A class-form site needs ``timezone`` bound; a module-form one rides its own import."""
    if module["has_tz"]:
        return False
    return any(
        item["kind"] == "site"
        and STYLES[module["bindings"][item["binding"]]["style"]][0] in ("class", "class_via_module")
        for item in module["items"]
    )


def _decoy_receiver(binding: dict[str, str]) -> tuple[str, str]:
    """(name, call-through-name) for a decoy that reuses the binding's own name."""
    form = STYLES[binding["style"]][0]
    name = binding["name"]
    if form == "class":
        return name, f"{name}.utcnow()"
    return name, f"{name}.datetime.utcnow()"


def _site_block(k: int, ctx: str, s: str) -> tuple[list[str], list[str]]:
    """Lines holding the site ``s`` (tagged), and the expressions that execute it."""
    tag = "  # S"
    if ctx == "module":
        return [f"h_v{k} = {s}{tag}"], []
    if ctx == "function":
        return [f"def h_f{k}():", f"    return {s}{tag}"], [f"h_f{k}()"]
    if ctx == "default_arg":
        return [f"def h_f{k}(x={s}):{tag}", "    return x"], [f"h_f{k}()"]
    if ctx == "lambda":
        return [f"h_f{k} = lambda: {s}{tag}"], [f"h_f{k}()"]
    if ctx == "fstring":
        return [f"def h_f{k}():", '    return f"at {' + s + '}"' + tag], [f"h_f{k}()"]
    if ctx == "fstring_conv":
        return [f"def h_f{k}():", '    return f"{' + s + '!r:>40}"' + tag], [f"h_f{k}()"]
    if ctx == "decorator":
        return [
            f"def h_deco{k}(value):",
            "    def wrap(fn):",
            "        return fn",
            "    return wrap",
            "",
            "",
            f"@h_deco{k}({s}){tag}",
            f"def h_g{k}():",
            "    return 1",
        ], [f"h_g{k}()"]
    if ctx == "class_body":
        return [f"class h_K{k}:", f"    stamp = {s}{tag}"], []
    if ctx == "comprehension":
        return [f"def h_f{k}():", f"    return [{s} for _ in range(2)]{tag}"], [f"h_f{k}()"]
    if ctx == "method":
        return [f"class h_K{k}:", "    def m(self):", f"        return {s}{tag}"], [f"h_K{k}().m()"]
    if ctx == "nested":
        return [
            f"def h_f{k}():",
            "    def inner():",
            f"        return {s}{tag}",
            "",
            "    return inner()",
        ], [f"h_f{k}()"]
    if ctx == "kwarg":
        return [f"h_v{k} = dict(when={s}){tag}"], []
    if ctx == "chained":
        return [f"h_v{k} = {s}.isoformat(){tag}"], []
    if ctx == "ternary":
        return [f"h_v{k} = {s} if h_v{k}_flag else None{tag}"], []
    raise ValueError(ctx)


def _decoy_block(k: int, ctx: str, binding: dict[str, str]) -> tuple[list[str], list[str]]:
    tag = "  # D"
    name, through = _decoy_receiver(binding)
    module_form = STYLES[binding["style"]][0] != "class"
    stand_in = f"h_NS{k}" if module_form else "h_Clock()"
    ns = [f"class h_NS{k}:", "    datetime = h_Clock()", "", ""] if module_form else []
    if ctx == "clock":
        return [f"h_c{k} = h_Clock().utcnow(){tag}"], []
    if ctx == "namespace_attr":
        return [
            f"class h_N{k}:",
            "    datetime = h_Clock()",
            "",
            "",
            f"h_d{k} = h_N{k}.datetime.utcnow(){tag}",
        ], []
    if ctx == "string":
        return [f'h_s{k} = "{through}"{tag}'], []
    if ctx == "comment":
        return [f"# {through}"], []
    if ctx == "docstring":
        return [f"def h_doc{k}():", f'    """Calls {through} somewhere."""', "    return 1"], [
            f"h_doc{k}()"
        ]
    if ctx == "shadow_local":
        return [*ns, f"def h_sh{k}():", f"    {name} = {stand_in}", f"    return {through}{tag}"], [
            f"h_sh{k}()"
        ]
    if ctx == "shadow_param":
        return [*ns, f"def h_sp{k}({name}):", f"    return {through}{tag}"], [
            f"h_sp{k}({stand_in})"
        ]
    if ctx == "bare_reference":
        attr = f"{name}.utcnow" if not module_form else f"{name}.datetime.utcnow"
        return [f"h_r{k} = {attr}{tag}"], []
    if ctx == "lambda_param":
        return [*ns, f"h_l{k} = lambda {name}: {through}{tag}"], [f"h_l{k}({stand_in})"]
    if ctx == "comprehension_var":
        return [*ns, f"h_q{k} = [{through} for {name} in [{stand_in}]]{tag}"], []
    if ctx == "class_body_shadow":
        return [*ns, f"class h_C{k}:", f"    {name} = {stand_in}", f"    v = {through}{tag}"], []
    raise ValueError(ctx)


PRELUDE = [
    "class h_Clock:",
    "    def utcnow(self):",
    "        return 0",
    "",
    "    def utcfromtimestamp(self, t):",
    "        return t",
    "",
    "",
]


def render_module(module: dict) -> tuple[str, list[tuple[str, str]]]:
    """Module source, plus [(old site text, new site text)] in line order."""
    imports = [STYLES[b["style"]][1].format(n=b["name"]) for b in module["bindings"]]
    if module["has_tz"]:
        imports.append("from datetime import timezone")
    body: list[str] = [*imports, "", "", *PRELUDE]
    runs: list[str] = []
    sites: list[tuple[str, str]] = []
    for k, item in enumerate(module["items"]):
        binding = module["bindings"][item["binding"]]
        if item["kind"] == "site":
            old, new = site_text(binding, item["method"])
            if item["ctx"] == "ternary":
                body.append(f"h_v{k}_flag = True")
            lines, calls = _site_block(k, item["ctx"], old)
            sites.append((old, new))
        else:
            lines, calls = _decoy_block(k, item["ctx"], binding)
        body += [*lines, "", ""]
        runs += calls
    body += ["def h_run():", *(f"    {c}" for c in runs), "    return None", ""]
    return "\n".join(body), sites


def render(spec: dict) -> dict[str, str]:
    """Repo-relative path -> source. Flat layout: ``pkg/`` at the repo root."""
    files = {
        "pkg/__init__.py": "",
        "pkg/compat.py": 'from datetime import datetime\n\n__all__ = ["datetime"]\n',
        "pkg/compat2.py": 'import datetime\n\n__all__ = ["datetime"]\n',
    }
    for i, module in enumerate(spec["modules"]):
        files[f"pkg/m{i}.py"] = render_module(module)[0]
    return files


def expected_source(module: dict) -> str:
    """What the module should read after migration, imports aside."""
    source, sites = render_module(module)
    lines = source.split("\n")
    pending = list(sites)
    for i, line in enumerate(lines):
        if line.endswith("  # S"):
            old, new = pending.pop(0)
            assert old in line
            lines[i] = line.replace(old, new, 1)
    assert not pending
    return "\n".join(lines)


def driver(spec: dict) -> str:
    """Python that imports every module and executes every site and decoy."""
    mods = [f"pkg.m{i}" for i in range(len(spec["modules"]))]
    return "\n".join([*(f"import {m}" for m in mods), *(f"{m}.h_run()" for m in mods)])
