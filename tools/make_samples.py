#!/usr/bin/env python3
"""Builds the two sample lesson bundles (validated by the shared models) and copies them into
the gateway seed data and the Android app assets so the app works offline with no backend."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libs" / "lessonkit"))

from lessonkit import Action, LessonBundle, LessonScript, LessonStep, Question  # noqa: E402


def W(text, x, y, color="white", size="m"):
    return Action(type="write", text=text, x=x, y=y, color=color, size=size)


def U(x, y, x2, color="yellow"):
    return Action(type="underline", x=x, y=y, x2=x2, y2=y, color=color)


def BOX(x, y, x2, y2, color="green"):
    return Action(type="box", x=x, y=y, x2=x2, y2=y2, color=color)


def ARROW(x, y, x2, y2, color="yellow"):
    return Action(type="arrow", x=x, y=y, x2=x2, y2=y2, color=color)


def S(i, say, *actions, pause=350):
    return LessonStep(id=f"s{i}", say=say, actions=list(actions), pause_ms=pause)


Q1 = Question(
    id="ssc-quant-0001", exam="SSC CGL", subject="algebra",
    text="If a⁴ + b⁴ + a²b² = 8 and a² + b² + ab = 4, then the value of ab is:",
    options=["(a) 3", "(b) 0", "(c) 2", "(d) 1"], correct_option="(d)",
)
Q1.options = ["(b) 0", "(c) 2", "(d) 1"]

q1_identity = LessonScript(
    question_id=Q1.id, title="Trick 1: Identity (10 seconds)", trick_id="alg-identity-a4-a2b2-b4",
    estimated_seconds=10, answer="ab = 1, option (d)",
    works_when="The question has a⁴ + a²b² + b⁴ and a² + ab + b².",
    steps=[
        S(1, "Dekho, pehli equation mein a to the power 4, a square b square, b to the power 4 hai, aur doosri mein a square, a b, b square. Yeh pattern pehchano!",
          W("a⁴ + b⁴ + a²b² = 8", 0.05, 0.10, size="l"), W("a² + b² + ab = 4", 0.05, 0.24, size="l")),
        S(2, "Yeh famous identity hai: a to the power 4 plus a square b square plus b to the power 4 barabar a square plus a b plus b square, into a square minus a b plus b square.",
          W("a⁴+a²b²+b⁴ = (a²+ab+b²)(a²−ab+b²)", 0.05, 0.42, "yellow"), U(0.05, 0.47, 0.88)),
        S(3, "Ab 8 ko likho, 4 into bracket. Kyunki a square plus a b plus b square ka value 4 hai.",
          W("8 = 4 × (a² − ab + b²)", 0.05, 0.58)),
        S(4, "Dono side 4 se divide karo. Mila a square plus b square minus a b barabar 2.",
          W("a² + b² − ab = 2", 0.05, 0.70, "green", "l")),
        S(5, "Ab dono equations ko subtract karo. a square aur b square cut ho gaye, bacha 2 a b barabar 2. To a b barabar 1.",
          W("(a²+b²+ab) − (a²+b²−ab) = 4 − 2", 0.05, 0.82), W("ab = 1", 0.62, 0.94, "green", "l"),
          BOX(0.58, 0.86, 0.80, 0.99)),
    ],
)

q1_subst = LessonScript(
    question_id=Q1.id, title="Trick 2: Substitution", trick_id="alg-sum-diff-substitution",
    estimated_seconds=25, answer="ab = 1, option (d)",
    works_when="You know a²+b²+ab and can rewrite a⁴+b⁴ using x = a²+b² and y = ab.",
    steps=[
        S(1, "Agar identity yaad nahi hai to substitution lagao. a square plus b square ko x maano, aur a b ko y.",
          W("x = a² + b²,   y = ab", 0.05, 0.10, size="l"), W("x + y = 4", 0.05, 0.24, "yellow")),
        S(2, "a to the power 4 plus b to the power 4 ko x square minus 2 y square likhte hain.",
          W("a⁴ + b⁴ = x² − 2y²", 0.05, 0.38)),
        S(3, "Pehli equation mein daalo: x square minus 2 y square plus y square, barabar 8. Yaani x square minus y square barabar 8.",
          W("x² − 2y² + y² = 8  ⇒  x² − y² = 8", 0.05, 0.52)),
        S(4, "x square minus y square ko (x minus y)(x plus y) likho. x plus y chaar hai, to x minus y barabar 2.",
          W("(x − y)(x + y) = 8  ⇒  x − y = 2", 0.05, 0.66, "yellow")),
        S(5, "x plus y chaar aur x minus y do ko jodo. 2x barabar 6, x barabar 3. Isliye y, yaani a b, barabar 1.",
          W("x = 3,  y = 1  ⇒  ab = 1", 0.05, 0.82, "green", "l"), BOX(0.03, 0.74, 0.62, 0.93)),
    ],
)

q1_options = LessonScript(
    question_id=Q1.id, title="Trick 3: Option elimination", trick_id="alg-option-backsolve",
    estimated_seconds=20, answer="ab = 1, option (d)",
    works_when="Options are small numbers that are quick to test.",
    steps=[
        S(1, "Options mein 0, 2 aur 1 hai. Sabse pehle 0 test karte hain.",
          W("a² + b² + ab = 4", 0.05, 0.10, size="l")),
        S(2, "Agar a b zero hota, to a square plus b square barabar 4 hota. Tab a to the power 4 plus b to the power 4 barabar 16 hota, 8 nahi. Option b out.",
          W("ab = 0 ⇒ a⁴ + b⁴ = 16 ≠ 8", 0.05, 0.30, "red")),
        S(3, "Ab a b barabar 2 lo. Tab a square plus b square barabar 2 aata hai, lekin a square plus b square kabhi 2 a b, yaani 4 se chhota nahi ho sakta. Option c out.",
          W("ab = 2 ⇒ a² + b² = 2 < 2ab = 4  ✗", 0.05, 0.50, "red")),
        S(4, "Ab a b barabar 1: a square plus b square barabar 3, a to the power 4 plus b to the power 4 barabar 9 minus 2, yaani 7. 7 plus 1 barabar 8. Sahi! Option d.",
          W("ab = 1 ⇒ a⁴ + b⁴ = 9 − 2 = 7,  7 + 1 = 8 ✓", 0.05, 0.72, "green"), BOX(0.03, 0.64, 0.92, 0.82)),
    ],
)

Q2 = Question(
    id="ssc-quant-0002", exam="SSC CGL", subject="algebra",
    text="If √(4x − 9) + √(4x + 9) = 5 + √7, then the value of x is:",
    options=["(a) 4", "(b) 5", "(c) 7", "(d) 3"], correct_option="(a)",
)

q2_rationalise = LessonScript(
    question_id=Q2.id, title="Trick 1: Subtract the pair", trick_id="alg-sqrt-pair-difference",
    estimated_seconds=15, answer="x = 4, option (a)",
    works_when="Two square roots whose insides differ by a constant, and their sum is given.",
    steps=[
        S(1, "Dono roots ke andar ka difference nikalo: 4x plus 9 minus 4x minus 9 barabar 18.",
          W("(4x+9) − (4x−9) = 18", 0.05, 0.10, "yellow", "l")),
        S(2, "To root ka difference barabar 18 divided by root ka sum.",
          W("√(4x+9) − √(4x−9) = 18 / (5 + √7)", 0.05, 0.28)),
        S(3, "5 plus root 7 into 5 minus root 7 barabar 25 minus 7, yaani 18. Isliye difference barabar 5 minus root 7.",
          W("= 5 − √7", 0.05, 0.44, "green")),
        S(4, "Dono ko jodo. 2 into root of 4x plus 9 barabar 10. Root barabar 5, to 4x plus 9 barabar 25.",
          W("2√(4x+9) = 10  ⇒  4x + 9 = 25", 0.05, 0.60)),
        S(5, "4x barabar 16, x barabar 4. Option a.", W("x = 4", 0.05, 0.80, "green", "l"), BOX(0.03, 0.72, 0.25, 0.92)),
    ],
)

q2_guess = LessonScript(
    question_id=Q2.id, title="Trick 2: Guess the roots (10 seconds)", trick_id="alg-sqrt-guess-perfect-square",
    estimated_seconds=10, answer="x = 4, option (a)",
    works_when="The right side is a whole number plus a surd, so one root is probably a perfect square.",
    steps=[
        S(1, "Right side dekho: 5 plus root 7. Guess karo ki ek root 5 hai, yaani root 25, aur doosra root 7.",
          W("5 + √7  =  √25 + √7", 0.05, 0.14, "yellow", "l")),
        S(2, "Agar 4x plus 9 barabar 25, to 4x barabar 16, x barabar 4.", W("4x + 9 = 25  ⇒  x = 4", 0.05, 0.40)),
        S(3, "Check karo: 4x minus 9 barabar 16 minus 9, yaani 7. Root 7 mil gaya. Option a sahi!",
          W("4x − 9 = 16 − 9 = 7  ✓", 0.05, 0.62, "green"), BOX(0.03, 0.54, 0.52, 0.72)),
    ],
)

BUNDLES = [LessonBundle(question=Q1, lessons=[q1_identity, q1_subst, q1_options]),
           LessonBundle(question=Q2, lessons=[q2_rationalise, q2_guess])]


def main() -> None:
    out_gateway = ROOT / "sample" / "bundles"
    out_android = ROOT / "android" / "app" / "src" / "main" / "assets" / "bundles"
    out_gateway.mkdir(parents=True, exist_ok=True)
    out_android.mkdir(parents=True, exist_ok=True)
    ids = []
    for b in BUNDLES:
        data = b.model_dump(mode="json", exclude_none=True)
        text = json.dumps(data, ensure_ascii=False, indent=2)
        (out_gateway / f"{b.question.id}.json").write_text(text, encoding="utf-8")
        (out_android / f"{b.question.id}.json").write_text(text, encoding="utf-8")
        ids.append(b.question.id)
    (out_android / "index.json").write_text(json.dumps(ids), encoding="utf-8")
    print("wrote", ids)


if __name__ == "__main__":
    main()
