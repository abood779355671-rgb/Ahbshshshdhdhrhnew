# DATABASE_MODE — Manual Patch Notes

`config.py` and `sample.env` were **not present** in the uploaded zip (only the
`UltraMusic/` package folder was included — `config.py` is imported in
`UltraMusic/__init__.py` as a top-level sibling module: `from config import
Config`, so it normally lives one level up, next to `UltraMusic/`).

Because I don't have the real file, I did **not** fabricate a full
replacement `config.py` — that risks silently dropping or guessing wrong
values for your other existing variables (API_ID, API_HASH, MONGO_URL, etc.).
Everything else in this zip (memory_db.py, the conditional db init in
`UltraMusic/__init__.py`) is already done and works as soon as you add the
line below — `UltraMusic/__init__.py` uses `getattr(config, "DATABASE_MODE",
"mongo")`, so it's safe even before you patch `config.py` (it'll just keep
using Mongo).

## 1. Add to `config.py`

Inside your `Config` class's `__init__`, alongside your other
`getenv(...)`-based variables, add:

```python
self.DATABASE_MODE: str = getenv("DATABASE_MODE", "mongo").lower()
```

(Exactly as you specified — default `"mongo"` so existing deployments are
unaffected unless this is set explicitly.)

## 2. Add to `sample.env`

```env
# DATABASE_MODE: "mongo" (default, real MongoDB) or "memory" (in-RAM, for
# quick local testing only). ⚠️ memory mode loses ALL data (sudoers, settings,
# blacklist, language, etc.) on every restart — never use it for a real
# production bot serving real users/groups.
DATABASE_MODE=mongo
```

## Usage once patched

```env
DATABASE_MODE=memory
```

No MongoDB connection will be attempted; `UltraMusic/core/memory_db.py`'s
`MemoryDB` class is used instead, with a startup warning logged.
