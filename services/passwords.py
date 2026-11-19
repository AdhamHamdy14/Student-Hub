import re


def password_meets_policy(password):
    return len(password) >= 8 and re.search(r"[0-9\W_]", password) is not None
