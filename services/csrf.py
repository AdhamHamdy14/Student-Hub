import secrets
from functools import wraps
from hmac import compare_digest

from flask import abort, request, session


def csrf_token():
    token = session.get("_csrf_token")
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def csrf_protect(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return view(*args, **kwargs)

        expected = session.get("_csrf_token")
        submitted = request.form.get("_csrf_token")
        if (
            not isinstance(expected, str)
            or not isinstance(submitted, str)
            or not compare_digest(expected, submitted)
        ):
            abort(400)
        return view(*args, **kwargs)

    return wrapped_view
