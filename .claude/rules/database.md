---
description: Database query patterns and MT5 call efficiency
globs: ["**/*.py", "**/db/**", "**/data-retriever/**"]
---

- Parameterized queries only; no N+1 patterns.
- Minimize MT5 calls and redundant DB writes.
- Memory-aware handling of candle data.
