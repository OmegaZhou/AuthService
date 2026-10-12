param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.@-]*$')]
    [string]$SshHost,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_.@+-]*$')]
    [string]$Username,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9][a-z0-9_.@+-]{0,319}$')]
    [string]$NewUsername,
    [switch]$Check
)
$ErrorActionPreference = 'Stop'
$remoteCommand = "sudo -- /usr/local/sbin/auth-service-rename-user --username $Username --new-username $NewUsername"
if ($Check) { $remoteCommand += ' --check' }
& ssh -t $SshHost $remoteCommand
if ($LASTEXITCODE -ne 0) { throw "Account reset exited with code $LASTEXITCODE" }
