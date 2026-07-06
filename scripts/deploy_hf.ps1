param(
    [Parameter(Position = 0)]
    [string]$SpaceId = $env:HF_SPACE_ID,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Show-Usage {
    Write-Host "Usage: .\scripts\deploy_hf.ps1 <user>/<space> [-Force]"
    Write-Host ""
    Write-Host "Pushes the current Git HEAD to the Hugging Face Docker Space main branch."
    Write-Host "Requires HF_TOKEN in the environment. Configure secrets in the Space UI."
}

if (-not $SpaceId -or $SpaceId -notmatch "^[^/]+/[^/]+$") {
    Show-Usage
    exit 2
}
if (-not $env:HF_TOKEN) {
    Write-Error "HF_TOKEN is required."
}

$owner = $SpaceId.Split("/")[0]
$remoteUrl = "https://${owner}:$($env:HF_TOKEN)@huggingface.co/spaces/$SpaceId.git"
$pushArgs = @($remoteUrl, "HEAD:main")
if ($Force) {
    $pushArgs += "--force"
}

Write-Host "Pushing current HEAD to Hugging Face Space $SpaceId..."
git push @pushArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
Write-Host "Deploy pushed. Watch the Space build logs in Hugging Face."
