# Decisions

- Use Python asyncio, FastAPI and tmux; no paid services.
- No host preview app is required. Only site/ is a product UI.
- Credential values are removed from the archived build brief.
- Cloudflare account-scoped token validates on the account endpoint, not the user-token endpoint. Deploy only static site/ to Pages.
