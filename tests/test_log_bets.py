from scripts.log_bets import _price_tip_upgrade


def test_a_tip_after_no_tip_is_logged_and_a_logged_tip_stands():
    no_tip, tip = {"tip": None, "reason": "..."}, {"tip": {"market": "1X2"}}
    assert _price_tip_upgrade(None, no_tip)
    assert _price_tip_upgrade(no_tip, tip)
    assert not _price_tip_upgrade(tip, {"tip": {"market": "BTTS"}})
    assert not _price_tip_upgrade(no_tip, no_tip)
