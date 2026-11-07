"""Machine checks used by the verifier service, the trick-library validator and the generator.

Check kinds:
  identity      lhs == rhs for all values of the variables (random numeric tests + exact test when possible)
  numeric       a closed-form number equals an expected number
  solve_target  the claimed value of `target` is the (only) real value over all real solutions of `givens`
  option_check  exactly the claimed option satisfies `equation`
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

import sympy as sp

from .safe_math import UnsafeExpression, make_symbols, safe_parse

TOL = 1e-8


@dataclass
class CheckResult:
    ok: bool
    detail: str = ""
    info: dict[str, Any] = field(default_factory=dict)


def _num(expr: sp.Expr) -> complex:
    return complex(sp.N(expr, 30))


def _close(a: complex, b: complex, tol: float = TOL) -> bool:
    return abs(a - b) <= tol * (1 + abs(a) + abs(b))


def _split_equation(text: str) -> tuple[str, str]:
    if "=" not in text:
        return text, "0"
    left, right = text.split("=", 1)
    return left, right


def check_identity(spec: dict) -> CheckResult:
    names = spec.get("vars", [])
    syms = make_symbols(names, spec.get("domain"))
    lhs, rhs = safe_parse(spec["lhs"], syms), safe_parse(spec["rhs"], syms)
    rng = random.Random(7)
    positive = spec.get("domain") == "positive"
    for _ in range(14):
        point = {s: (rng.uniform(1.0, 6.0) if positive else rng.uniform(0.3, 1.2)) for s in syms.values()}
        try:
            a, b = _num(lhs.subs(point)), _num(rhs.subs(point))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if not _close(a, b):
            return CheckResult(False, f"differs at {point}: {a} vs {b}")
    exact = None
    if not (lhs.has(sp.Function) or rhs.has(sp.sin, sp.cos, sp.tan, sp.cot, sp.sec, sp.csc) or lhs.has(sp.sin, sp.cos, sp.tan, sp.cot, sp.sec, sp.csc)):
        try:
            exact = sp.simplify(lhs - rhs) == 0
        except Exception:  # noqa: BLE001
            exact = None
    if exact is False and not positive:
        return CheckResult(False, "numeric tests passed but exact simplification is non-zero", {"exact": False})
    return CheckResult(True, "identity holds on 14 random points", {"exact": exact})


def check_numeric(spec: dict) -> CheckResult:
    got, want = safe_parse(spec["expr"]), safe_parse(str(spec["expected"]))
    ok = _close(_num(got), _num(want))
    return CheckResult(ok, f"{sp.N(got)} vs {sp.N(want)}")


def _real_target_values(givens: list[str], names: list[str], target: str) -> list[float]:
    syms = make_symbols(names)
    eqs = []
    for g in givens:
        l, r = _split_equation(g)
        eqs.append(safe_parse(l, syms) - safe_parse(r, syms))
    tgt = safe_parse(target, syms)
    values: list[float] = []
    try:
        sols = sp.solve(eqs, list(syms.values()), dict=True)
    except Exception:  # noqa: BLE001
        sols = []
    for sol in sols:
        try:
            if not all(abs(complex(sp.N(v)).imag) < 1e-9 for v in sol.values()):
                continue
            tv = complex(sp.N(tgt.subs(sol)))
            if abs(tv.imag) < 1e-9:
                values.append(tv.real)
        except (TypeError, ValueError):
            continue
    if not values:  # numeric fallback: random-start Newton
        rng = random.Random(3)
        free = list(syms.values())
        for _ in range(60):
            guess = [rng.uniform(-4, 4) for _ in free]
            try:
                root = sp.nsolve(eqs, free, guess, tol=1e-12, maxsteps=60)
                point = dict(zip(free, [float(v) for v in root]))
                values.append(float(sp.N(tgt.subs(point))))
            except Exception:  # noqa: BLE001
                continue
    return values


def check_solve_target(spec: dict) -> CheckResult:
    values = _real_target_values(spec["givens"], spec["vars"], spec["target"])
    if not values:
        return CheckResult(False, "no real solutions found")
    claimed = float(sp.N(safe_parse(str(spec["claimed"]))))
    distinct = sorted({round(v, 6) for v in values})
    ok = all(abs(v - claimed) < 1e-6 for v in distinct)
    return CheckResult(ok, f"real values of target: {distinct}", {"values": distinct})


def check_option(spec: dict) -> CheckResult:
    var = spec["var"]
    syms = make_symbols([var])
    l, r = _split_equation(spec["equation"])
    expr = safe_parse(l, syms) - safe_parse(r, syms)
    good = []
    for label, val in spec["options"].items():
        try:
            if abs(_num(expr.subs(syms[var], safe_parse(str(val))))) < 1e-8:
                good.append(label)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    ok = good == [spec["claimed"]]
    return CheckResult(ok, f"options satisfying the equation: {good}", {"satisfying": good})


CHECKS = {
    "identity": check_identity,
    "numeric": check_numeric,
    "solve_target": check_solve_target,
    "option_check": check_option,
}


def run_check(spec: dict) -> CheckResult:
    kind = spec.get("kind")
    fn = CHECKS.get(kind)
    if fn is None:
        return CheckResult(False, f"unknown check kind: {kind!r}")
    try:
        return fn(spec)
    except UnsafeExpression as exc:
        return CheckResult(False, f"rejected expression: {exc}")
    except KeyError as exc:
        return CheckResult(False, f"missing field {exc}")
