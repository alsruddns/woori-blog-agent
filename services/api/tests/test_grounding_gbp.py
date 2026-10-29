from woori.grounding import numbers


def test_gbp_source_units_match_korean_scale_words() -> None:
    assert numbers("£3,005 billion") == numbers("3조 50억 파운드")
    assert numbers("£24.5 billion") == numbers("245억 파운드")


def test_gbp_unit_check_still_rejects_changed_values_and_currency() -> None:
    assert numbers("£24.5 billion") != numbers("246억 파운드")
    assert numbers("£24.5 billion") != numbers("245억 원")
