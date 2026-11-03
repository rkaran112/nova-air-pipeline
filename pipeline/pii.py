"""Turn personal data into keyed tokens (HMAC-SHA256) that SQL can call as pii_token().

A plain hash is not enough: anyone can hash a list of guessed emails and match them.
HMAC mixes in a secret key first, so without the key nobody can recreate a token.
The same value and key always give the same token, so tokens still join.
"""

import hashlib
import hmac


def make_tokenizer(key):
    key_bytes = key.encode("utf-8")

    def pii_token(value):
        return hmac.new(key_bytes, value.encode("utf-8"), hashlib.sha256).hexdigest()

    return pii_token


def register_pii_function(con, key):
    # DuckDB skips the function for NULL inputs and returns NULL, which is what we want.
    con.create_function("pii_token", make_tokenizer(key), ["VARCHAR"], "VARCHAR")
