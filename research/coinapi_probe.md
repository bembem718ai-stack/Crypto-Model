# CoinAPI acceptance probe — NOT RUN

**COINAPI_KEY was not present in this process's environment**, so no
request was made and no credit was spent.

Checked: the Bash tool environment, the PowerShell session, and the
Windows User and Machine environment scopes. Not set in any of them,
and no `.env`/secret file in the repo carries it.

Most likely cause: the variable was set in an interactive shell, and
each tool call starts a new process that does not inherit it.

To make it visible to this script, either persist it for new
processes (PowerShell, once):

    [Environment]::SetEnvironmentVariable('COINAPI_KEY','<key>','User')

or set it inline for the single command that runs the probe. Do not
paste the key into chat — it would land in the transcript.

Requests used: **0**. Nothing registered, nothing scored.
