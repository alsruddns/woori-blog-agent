from woori.grounding import numbers


def test_gbp_source_units_match_korean_scale_words() -> None:
    assert numbers("£3,005 billion") == numbers("3조 50억 파운드")
    assert numbers("£24.5 billion") == numbers("245억 파운드")


def test_gbp_unit_check_still_rejects_changed_values_and_currency() -> None:
    assert numbers("£24.5 billion") != numbers("246억 파운드")
    assert numbers("£24.5 billion") != numbers("245억 원")


def test_month_ranges_and_ambiguous_month_amounts_do_not_create_false_numbers() -> None:
    month_amount = "2026년 9월 중앙정부 이자 지급액은 109억 파운드였습니다."
    assert "FACT:GBP:900000000" not in numbers(month_amount)
    assert "FACT:GBP:10900000000" in numbers(month_amount)
    assert numbers("같은 4~9월 기간 중 열 번째로 높았다") == numbers(
        "10th highest April-to-September figure"
    )
