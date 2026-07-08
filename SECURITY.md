# Security Policy

Report suspected vulnerabilities privately by opening a GitHub security advisory
or by contacting the maintainers directly.

Do not include production credentials, access tokens, recordings, transcripts,
or customer data in public issues.

The SDK reads service endpoints and client credentials from explicit CLI flags
or environment variables. Prefer environment variables for secrets and avoid
putting client secrets into shell history.
