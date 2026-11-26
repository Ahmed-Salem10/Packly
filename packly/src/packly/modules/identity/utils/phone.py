import re

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_EG_MOBILE = re.compile(r"^1[0125]\d{8}$")  # 010 / 011 / 012 / 015 + 8 digits


class InvalidPhoneError(ValueError):
    pass


def normalize_phone(raw: str) -> str:
    s = raw.translate(_DIGITS)
    s = re.sub(r"[\s\-().]", "", s)

    if s.startswith("+"):
        s = s[1:]
    elif s.startswith("00"):
        s = s[2:]

    if s.startswith("20"):
        s = s[2:]
    elif s.startswith("0"):
        s = s[1:]

    if not _EG_MOBILE.match(s):
        raise InvalidPhoneError(f"Invalid Egyptian mobile number: {raw!r}")
    return f"+20{s}"
