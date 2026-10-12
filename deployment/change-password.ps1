param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.@-]*$')]
    [string]$SshHost,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.@+-]*$')]
    [string]$Username,
    [switch]$Check
)
$ErrorActionPreference = 'Stop'
# Password entry happens on the SSH terminal, never in arguments or a local file.
$remoteCommand = "sudo -- /usr/local/sbin/gpt-plugin-oauth-password --username $Username"
if ($Check) { $remoteCommand += ' --check' }
& ssh -t $SshHost $remoteCommand
if ($LASTEXITCODE -ne 0) { throw "Password tool exited with code $LASTEXITCODE" }
