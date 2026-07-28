from __future__ import annotations

from build_prompt_matrix_contact_sheets import _sheet_chunks


def cases(count: int, mode: str = "mass_axis_camera") -> list[tuple[str, str]]:
    return [(mode, f"item_{index:03d}") for index in range(1, count + 1)]


def test_consecutive_chunking_is_still_the_default() -> None:
    chunks = _sheet_chunks(cases(250), cases_per_sheet=10, spread=False)
    assert len(chunks) == 25
    assert [case[1] for case in chunks[0]][:3] == ["item_001", "item_002", "item_003"]


def test_spread_strides_across_the_sorted_list() -> None:
    """Combinatorial catalogs sort near-duplicates adjacently.

    The first Phase 7 camera sheet held ten chest_up clean_profile variants, so
    an unresponsive axis looked consistent instead of broken.
    """
    chunks = _sheet_chunks(cases(250), cases_per_sheet=10, spread=True)
    assert len(chunks) == 25
    assert [case[1] for case in chunks[0]][:3] == ["item_001", "item_026", "item_051"]


def test_both_modes_cover_every_case_exactly_once() -> None:
    for count in (12, 60, 250, 326, 500):
        for spread in (False, True):
            chunks = _sheet_chunks(cases(count), cases_per_sheet=10, spread=spread)
            flat = [case for chunk in chunks for case in chunk]
            assert len(flat) == count, (count, spread)
            assert len(set(flat)) == count, (count, spread)
            assert all(chunk for chunk in chunks), (count, spread)


def test_spread_respects_the_sheet_budget() -> None:
    """Striding must not produce more sheets or oversized sheets."""
    for count in (12, 60, 250, 326, 500):
        consecutive = _sheet_chunks(cases(count), cases_per_sheet=10, spread=False)
        spread = _sheet_chunks(cases(count), cases_per_sheet=10, spread=True)
        assert len(spread) == len(consecutive), count
        assert max(len(chunk) for chunk in spread) <= 10, count


def test_a_single_sheet_is_unaffected_by_spreading() -> None:
    consecutive = _sheet_chunks(cases(4), cases_per_sheet=10, spread=False)
    spread = _sheet_chunks(cases(4), cases_per_sheet=10, spread=True)
    assert consecutive == spread == [cases(4)]
