"""Data governance: every source column carries a sensitivity label, and the labels are used.

The labels live in config/pipeline.toml under [classification.<source>]. The tests in
test_pii.py read the "pii" labels to know what must never appear raw in silver, gold or
the exports; the tests here check that the labels are complete and valid.
"""

from pipeline.settings import load_config

ALLOWED_LABELS = {"public", "internal", "pii"}


def test_every_label_is_one_of_the_allowed_three():
    for source, columns in load_config()["classification"].items():
        assert set(columns.values()) <= ALLOWED_LABELS, source


def test_every_required_column_has_a_label():
    config = load_config()
    for source, spec in config["sources"].items():
        unlabelled = set(spec["required_columns"]) - set(config["classification"][source])
        assert not unlabelled, f"{source}: {sorted(unlabelled)}"


def test_only_the_unlabelled_fixture_column_is_flagged(warehouse):
    # The fixtures add one column (bookings.promo_code) that has no label on purpose.
    # Every other column in all three sources is labelled, so only that one is flagged.
    flagged = warehouse.execute("""
        SELECT DISTINCT source, check_name FROM meta.dq_results
        WHERE check_name LIKE 'column_unclassified:%'""").fetchall()
    assert flagged == [("bookings", "column_unclassified:promo_code")]
    assert warehouse.execute("""
        SELECT DISTINCT severity FROM meta.dq_results
        WHERE check_name LIKE 'column_unclassified:%'""").fetchall() == [("warn",)]
