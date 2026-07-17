# Privacy verification

Privacy regression tests must inspect the raw SQLite bytes, not only parsed rows. The test corpus includes API keys, bearer/JWT-like tokens, email addresses, phone/long-digit values, absolute paths, credential-bearing URLs, and high-entropy candidates.

All new persistence surfaces must use `maces.secure_store.CognitiveStore`; bypassing it requires an explicit security review.
