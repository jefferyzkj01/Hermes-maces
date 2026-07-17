# Installation Gate

Do not enable MACES outside shadow mode until both CI jobs pass:

- `unit-security`: Ruff plus unit, privacy, concurrency, cap, migration, Chinese extraction, and lifecycle tests;
- `hermes-plugin-manager-e2e`: discovery, enabled/disabled behavior, raw command dispatch, profile isolation, tool gates, concurrent hooks, pending cleanup, DB/WAL/SHM scanning, staging exclusion, and host sentinel integrity using `hermes-agent==0.18.2`.

The historical layout smoke test alone is not an installation gate.
