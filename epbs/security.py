"""Legacy MyMod cipher (reversible character shift).

Kept so existing tbl_users passwords keep working after migration:
    A-Z +127, a-z +121, 0-9 +196, everything else unchanged.
"""
from __future__ import annotations


def encrypt(text: str) -> str:
    out = []
    for ch in text or "":
        o = ord(ch)
        if "A" <= ch <= "Z":
            out.append(chr(o + 127))
        elif "a" <= ch <= "z":
            out.append(chr(o + 121))
        elif "0" <= ch <= "9":
            out.append(chr(o + 196))
        else:
            out.append(ch)
    return "".join(out)


def decrypt(text: str) -> str:
    out = []
    for ch in text or "":
        o = ord(ch)
        if 127 <= o <= 152:          # A-Z encrypted
            out.append(chr(o - 127))
        elif 218 <= o <= 243:        # a-z encrypted
            out.append(chr(o - 121))
        elif 244 <= o <= 253:        # 0-9 encrypted
            out.append(chr(o - 196))
        else:
            out.append(ch)
    return "".join(out)
