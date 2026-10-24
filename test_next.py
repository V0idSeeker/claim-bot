"""Self-check for the next-free math and chain check. No Discord/GitHub needed: `python test_next.py`."""
from bot import chain_problems, next_free, parse_numbers, parse_revision, prune

names = ["0065_x.py", "0066_regle_attribution.py", "__init__.py", "README.md"]
committed, width = parse_numbers(names, r"^(\d{4})_")
assert committed == {65, 66} and width == 4

assert next_free(committed, set()) == 67
assert next_free(committed, {67}) == 68      # claimed but unpushed number is skipped
assert next_free(committed, {47}) == 67      # old gap claim doesn't move the max
assert next_free(set(), set()) == 1
assert parse_numbers([], r"^(\d{4})_") == (set(), 4)

claims = {"0047": {}, "0066": {}, "0067": {}}
assert prune(claims, committed) == {"0047": {}, "0067": {}}  # 0066 was pushed

# --- migration chain ---
def mig(rev, down):
    return f'"""doc"""\nimport x\nrevision = {rev!r}\ndown_revision: str | None = {down!r}\n'

assert parse_revision(mig("0002", "0001")) == ("0002", ["0001"])
assert parse_revision(mig("m", ("a", "b"))) == ("m", ["a", "b"])       # merge revision
assert parse_revision(mig("0001", None)) == ("0001", [])

ok = {"0001_a.py": mig("0001", None), "0002_b.py": mig("0002", "0001"), "0003_c.py": mig("0003", "0002")}
assert chain_problems(ok, r"^(\d+)_") == ([], ["0003"])

forked = {**ok, "0003_d.py": mig("0003b", "0002")}                       # two people off the same parent
problems, heads = chain_problems(forked, r"^(\d+)_")
assert heads == ["0003", "0003b"]
assert any("2 heads" in p for p in problems) and any("number 0003" in p for p in problems)

assert chain_problems({**forked, "0004_m.py": mig("0004", ("0003", "0003b"))})[0] == []  # merged, no pattern

problems, _ = chain_problems({**ok, "0004_x.py": mig("0004", "0099"), "0005_y.py": mig("0002", "0004")})
assert any("`0099` doesn't exist" in p for p in problems)
assert any("revision `0002` is in both" in p for p in problems)
assert chain_problems({"bad.py": "def ("})[0][0].startswith("`bad.py`: can't read")

print("ok")
