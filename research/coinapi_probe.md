# CoinAPI acceptance probe — NOT RUN

**No key was reachable**, so no request was made and no credit was
spent.

Two sources are checked, in order: the `COINAPI_KEY` environment
variable, and a `.coinapi_key` file in the repo root. Neither was
present. The Windows User and Machine environment scopes were also
checked directly and are unset.

Most likely cause: the variable was set in an interactive shell, and
each tool call starts a separate process that does not inherit it.

Either of these makes it visible, no restart needed:

    # option A — a local file, already in .gitignore
    Set-Content -Path .coinapi_key -Value '<key>' -NoNewline

    # option B — persist for new processes, once
    [Environment]::SetEnvironmentVariable('COINAPI_KEY','<key>','User')

Do not paste the key into chat — it would land in the transcript.

Requests used: **0**. Nothing registered, nothing scored.
