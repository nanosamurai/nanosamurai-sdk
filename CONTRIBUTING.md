# Contributing

Before opening a pull request:

- keep secrets out of git
- run `python -m pip install -e ".[dev]"`
- run `ruff check .`
- run `pytest -q`
- document user-facing CLI or API changes in `README.md`

The SDK must remain self-hosting friendly: the API URL and OIDC issuer must
remain configurable. Use neutral hosts such as `example.com` or `example.test`
in examples and tests.
