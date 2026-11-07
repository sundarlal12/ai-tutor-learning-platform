"""Safe parsing of maths strings (they may come from an LLM, so treat them as untrusted input).

SymPy's parse_expr uses eval(). We therefore (1) allow only a tiny character set, (2) allow only
declared variable names and a whitelist of functions, (3) strip builtins, and (4) refuse chained
or huge powers that could be used for denial of service.
"""
from __future__ import annotations

import re

import sympy as sp
from sympy.parsing.sympy_parser import convert_xor, parse_expr, standard_transformations

MAX_LEN = 300
_ALLOWED_CHARS = re.compile(r"^[A-Za-z0-9_+\-*/^().,\s]*$")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CHAINED_POWER = re.compile(r"\*\*\s*-?\w+\s*\*\*|\*\*\s*\([^)]*\*\*")
_BIG_EXPONENT = re.compile(r"\*\*\s*(\d{5,})")

ALLOWED_FUNCS = {
    "sqrt": sp.sqrt, "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "cot": sp.cot,
    "sec": sp.sec, "csc": sp.csc, "log": sp.log, "ln": sp.log, "exp": sp.exp,
    "Abs": sp.Abs, "floor": sp.floor, "Mod": sp.Mod, "gcd": sp.gcd, "lcm": sp.lcm,
    "divisor_count": sp.divisor_count, "pi": sp.pi, "E": sp.E,
}

_GLOBALS = {
    "Integer": sp.Integer, "Float": sp.Float, "Rational": sp.Rational,
    "Symbol": sp.Symbol, "Function": sp.Function, "Wild": sp.Wild, "Dummy": sp.Dummy,
    "__builtins__": {},
}


class UnsafeExpression(ValueError):
    pass


def make_symbols(names: list[str], domain: str | None = None) -> dict[str, sp.Symbol]:
    kwargs = {}
    if domain == "positive":
        kwargs["positive"] = True
    elif domain == "real":
        kwargs["real"] = True
    out = {}
    for n in names:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,15}", n) or n in ALLOWED_FUNCS:
            raise UnsafeExpression(f"bad variable name: {n!r}")
        out[n] = sp.Symbol(n, **kwargs)
    return out


def safe_parse(text: str, symbols: dict[str, sp.Symbol] | None = None) -> sp.Expr:
    symbols = symbols or {}
    if not isinstance(text, str) or not text.strip():
        raise UnsafeExpression("empty expression")
    if len(text) > MAX_LEN:
        raise UnsafeExpression("expression too long")
    s = text.replace("^", "**").replace("×", "*").replace("÷", "/").replace("−", "-")
    if not _ALLOWED_CHARS.match(s.replace("**", "^")):
        raise UnsafeExpression("illegal characters")
    if "__" in s or _CHAINED_POWER.search(s) or _BIG_EXPONENT.search(s):
        raise UnsafeExpression("unsafe power or dunder")
    for name in _NAME.findall(s):
        if name not in ALLOWED_FUNCS and name not in symbols:
            raise UnsafeExpression(f"unknown name: {name}")
    local = {**ALLOWED_FUNCS, **symbols}
    try:
        return parse_expr(s, local_dict=local, global_dict=dict(_GLOBALS),
                          transformations=standard_transformations + (convert_xor,), evaluate=True)
    except UnsafeExpression:
        raise
    except Exception as exc:  # noqa: BLE001 - surface any parser failure uniformly
        raise UnsafeExpression(f"cannot parse {text!r}: {exc}") from exc
