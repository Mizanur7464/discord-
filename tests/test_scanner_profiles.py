from bot.trading.scanner_profiles import DEFAULT_PROFILES, load_profiles_from_config


def test_default_premarket_turnover_floor_is_one_million():
    assert DEFAULT_PROFILES["premarket"].min_turnover_usd == 1_000_000


def test_config_premarket_turnover_floor_can_match_buyer_requirement():
    profiles = load_profiles_from_config(
        {
            "premarket": {
                "min_turnover_usd": 1_000_000,
            }
        }
    )
    assert profiles["premarket"].min_turnover_usd == 1_000_000
