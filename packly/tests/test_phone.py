import pytest

from packly.modules.identity.utils.phone import InvalidPhoneError, normalize_phone


@pytest.mark.parametrize(
    "raw",
    [
        "01012345678",
        "+201012345678",
        "00201012345678",
        "201012345678",
        "010 1234 5678",
        "010-1234-5678",
        "+20 (10) 1234 5678",
        "٠١٠١٢٣٤٥٦٧٨",
    ],
)
def test_valid(raw):
    assert normalize_phone(raw) == "+201012345678"


@pytest.mark.parametrize(
    "raw", ["", "0101234567", "01312345678", "0225747000", "+14155550123", "abc"]
)
def test_invalid(raw):
    with pytest.raises(InvalidPhoneError):
        normalize_phone(raw)
