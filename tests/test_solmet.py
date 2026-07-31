"""Verification of the metric extractor against hand-computed values.

The reference contract below is small enough to count by hand, which is the
only way to know the extractor measures what it claims. Expected values are
derived in the comments so a reviewer can re-check them.
"""
from pathlib import Path

from sccomplex.metrics.solmet import extract_corpus, parse_file

FIXTURE = Path(__file__).parent / "fixtures" / "reference.sol"


def _by_name(rows):
    return {r.name: r for r in rows}


def test_declarations_found():
    rows = _by_name(parse_file(FIXTURE))
    assert set(rows) == {"Base", "IThing", "L", "Demo"}
    assert rows["IThing"].kind == "interface"
    assert rows["L"].kind == "library"
    assert rows["Demo"].kind == "contract"


def test_numpar_excludes_return_parameters():
    """Demo: ping() -> 0 inputs, complex(uint,uint,address) -> 3 inputs.

    onlyOwner() -> 0, constructor() -> 0. Total NUMPAR == 3.
    A naive count of `parameter` nodes yields 5 here because `returns (bool)`
    and `returns (uint)` also produce `parameter` nodes.
    """
    assert _by_name(parse_file(FIXTURE))["Demo"].NUMPAR == 3


def test_function_count():
    """Demo declares: modifier, constructor, ping, complex == 4."""
    assert _by_name(parse_file(FIXTURE))["Demo"].NF == 4


def test_mccabe_and_nesting():
    demo = _by_name(parse_file(FIXTURE))["Demo"]
    # complex(): 1 base + if + for + nested-if + while + else-if + catch
    #            + 2 ternaries == 9.  ping()/constructor()/onlyOwner() == 1 each.
    assert demo.WMC == 12
    # Deepest nesting in complex(): if > for > while == 3. Others 0.
    assert demo.NL == 3


def test_state_variables():
    """counter, balances, owner == 3 (Base.x belongs to Base)."""
    rows = _by_name(parse_file(FIXTURE))
    assert rows["Demo"].NA == 3
    assert rows["Base"].NA == 1


def test_inheritance_graph():
    df = extract_corpus([FIXTURE], progress=False).set_index("name")
    # Demo is Base, IThing -> 2 ancestors, depth 1; Base has 1 descendant.
    assert df.loc["Demo", "NOA"] == 2
    assert df.loc["Demo", "DIT"] == 1
    assert df.loc["Base", "NOD"] == 1
    assert df.loc["Demo", "NOD"] == 0


def test_comment_lines_are_not_logical_lines():
    df = extract_corpus([FIXTURE], progress=False).set_index("name")
    for name in df.index:
        assert df.loc[name, "LLOC"] + df.loc[name, "CLOC"] <= df.loc[name, "SLOC"]


def test_averages_defined_without_functions():
    """A contract with no functions must not divide by zero."""
    df = extract_corpus([FIXTURE], progress=False).set_index("name")
    assert df.loc["Base", "NF"] == 0
    assert df.loc["Base", "AvgMcCC"] == 0.0


def test_all_21_metrics_present():
    from sccomplex.config import SOLMET_METRICS

    df = extract_corpus([FIXTURE], progress=False)
    assert not set(SOLMET_METRICS) - set(df.columns)


def test_inheritance_is_scoped_per_file(tmp_path):
    """Identically named contracts in different files must not share a graph.

    Regression test: a corpus-wide name-keyed graph merges every `Ownable` in
    the corpus into one node, which produced NOD values in the hundreds.
    """
    a = tmp_path / "a.sol"
    b = tmp_path / "b.sol"
    a.write_text("contract Ownable { } contract A is Ownable { }")
    b.write_text("contract Ownable { } contract B is Ownable { }")

    df = extract_corpus([a, b], progress=False)
    owners = df[df["name"] == "Ownable"]
    assert len(owners) == 2
    # Each Ownable has exactly one descendant, in its own file -- not two.
    assert set(owners["NOD"]) == {1}
