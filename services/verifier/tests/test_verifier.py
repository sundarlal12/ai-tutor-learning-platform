from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

AB = {
    "kind": "solve_target", "vars": ["a", "b"],
    "givens": ["a**4 + b**4 + a**2*b**2 = 8", "a**2 + b**2 + a*b = 4"],
    "target": "a*b",
}


def verify(*checks):
    r = client.post("/verify", json={"checks": list(checks)})
    assert r.status_code == 200, r.text
    return r.json()


def test_health():
    assert client.get("/health").json()["status"] == "ok"


def test_ab_equals_1_is_accepted():
    out = verify({**AB, "claimed": "1"})
    assert out["all_ok"] is True


def test_wrong_claim_is_rejected():
    out = verify({**AB, "claimed": "2"})
    assert out["all_ok"] is False


def test_option_check_picks_exactly_one_option():
    spec = {
        "kind": "option_check", "var": "x",
        "equation": "sqrt(4*x - 9) + sqrt(4*x + 9) = 5 + sqrt(7)",
        "options": {"(a)": "4", "(b)": "5", "(c)": "7", "(d)": "3"},
    }
    assert verify({**spec, "claimed": "(a)"})["all_ok"] is True
    assert verify({**spec, "claimed": "(b)"})["all_ok"] is False


def test_identity_true_and_false():
    good = {"kind": "identity", "vars": ["a", "b"],
            "lhs": "a**4 + a**2*b**2 + b**4", "rhs": "(a**2 + a*b + b**2)*(a**2 - a*b + b**2)"}
    bad = {**good, "rhs": "(a**2 + a*b + b**2)*(a**2 + a*b + b**2)"}
    assert verify(good)["all_ok"] is True
    assert verify(bad)["all_ok"] is False


def test_trig_identity():
    spec = {"kind": "identity", "vars": ["t"], "lhs": "sin(t)**4 + cos(t)**4", "rhs": "1 - 2*sin(t)**2*cos(t)**2"}
    assert verify(spec)["all_ok"] is True


def test_code_injection_is_rejected():
    for evil in ["__import__('os').system('id')", "open('/etc/passwd')", "().__class__", "9**9**9"]:
        out = verify({"kind": "numeric", "expr": evil, "expected": "0"})
        assert out["all_ok"] is False
        assert "rejected" in out["results"][0]["detail"]


def test_unknown_kind_and_limits():
    assert verify({"kind": "magic"})["all_ok"] is False
    r = client.post("/verify", json={"checks": []})
    assert r.status_code == 400
    r = client.post("/verify", json={"checks": [{"kind": "numeric", "expr": "1", "expected": "1"}] * 21})
    assert r.status_code == 400
