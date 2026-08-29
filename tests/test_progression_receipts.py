from hund.learning.receipts import PublicProgressReceipt, format_public_receipt


def test_public_progress_receipt_formatting_no_uuids_or_raw_enums():
    # Skill XP receipt
    receipt_skill = PublicProgressReceipt(
        system="skill",
        entity="marketing",
        delta_xp=2,
        new_total=14,
        new_tier="Novice",
        reason="verified first use",
        timestamp="2026-08-26T12:00:00Z",
    )
    formatted_skill = format_public_receipt(receipt_skill)
    assert formatted_skill == "marketing       +2 skill XP · verified first use"
    assert "uuid" not in formatted_skill.lower()
    assert "event_" not in formatted_skill

    # Domain XP receipt
    receipt_domain = PublicProgressReceipt(
        system="domain",
        entity="python",
        delta_xp=5,
        new_total=45,
        new_tier="Novice",
        reason="verified cross-session reuse",
        timestamp="2026-08-26T12:00:00Z",
    )
    formatted_domain = format_public_receipt(receipt_domain)
    assert formatted_domain == "python          +5 domain XP · verified cross-session reuse"
    assert "uuid" not in formatted_domain.lower()

    # Base stat receipt
    receipt_stat = PublicProgressReceipt(
        system="base_stat",
        entity="Endurance",
        delta_xp=0,
        new_total=72,
        new_tier="",
        reason="8 of 11 sustained tasks verified",
        timestamp="2026-08-26T12:00:00Z",
    )
    formatted_stat = format_public_receipt(receipt_stat)
    assert formatted_stat == "Endurance       improved to 72% · 8 of 11 sustained tasks verified"
