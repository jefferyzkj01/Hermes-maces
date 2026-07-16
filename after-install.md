# Hermes MACES installed

The subconscious layer is installed and enabled.

Restart Hermes so the plugin can register its lifecycle hooks. MACES will then begin passively absorbing operator-driven traces and may inject a small advisory block before later turns.

Local state is stored inside the plugin directory at `data/subconscious.db`.

To disable it without affecting Hermes memory or Obsidian:

```bash
hermes plugins disable hermes-maces
```

To remove it completely:

```bash
hermes plugins remove Hermes-maces
```
