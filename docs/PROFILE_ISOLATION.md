# Profile isolation contract

A MACES runtime is created per plugin registration and permanently bound to `ctx.profile_name`. Runtime hooks close over that profile-bound instance. Profile identifiers supplied through hook kwargs, tool args, command params, or model output are ignored and cannot redirect storage.

Registration fails if `ctx.profile_name` is absent or invalid. There is no shared fallback database.
