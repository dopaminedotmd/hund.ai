from hund.specializations.flags import SpecializationFeatureFlags, feature_flags_from_mapping


def test_all_specialization_flags_default_off() -> None:
    flags = SpecializationFeatureFlags()

    assert flags.read_enabled is False
    assert flags.proposals_enabled is False
    assert flags.activation_enabled is False
    assert flags.progression_enabled is False


def test_flags_are_independent_and_ignore_invalid_values() -> None:
    flags = feature_flags_from_mapping({
        "specializations_read_enabled": True,
        "specializations_proposals_enabled": True,
        "specializations_activation_enabled": "yes",
        "specializations_progression_enabled": False,
    })

    assert flags == SpecializationFeatureFlags(True, True, False, False)
