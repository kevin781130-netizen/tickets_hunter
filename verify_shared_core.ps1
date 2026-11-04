# Non-booking integration gate for reusable reservation primitives.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$expectedBranch = 'refactor/shared-booking-core-20261104'
$branch = (& git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $branch -ne $expectedBranch) {
    throw "Wrong branch '$branch'. Expected '$expectedBranch'. The frozen RC must not be edited."
}
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Missing Python virtual environment: $python"
}

$modules = @(
    'src\reservation_common.py',
    'src\reservation_browser.py',
    'src\ncl_openlab_autobook.py',
    'src\platforms\ncl_openlab.py',
    'src\nodriver_tixcraft.py',
    'src\ncl_openlab_launcher.py',
    'src\ncl_openlab_picker_model.py',
    'src\ncl_openlab_picker.py',
    'src\ncl_browser_lifecycle_smoke.py'
)
& $python -m py_compile @modules
if ($LASTEXITCODE -ne 0) { throw 'COMPILE_FAILED' }

& $python -m unittest discover -s tests -p 'test_ncl_openlab_*.py' -q
if ($LASTEXITCODE -ne 0) { throw 'OFFLINE_TESTS_FAILED' }

Write-Host 'NCL_SHARED_CORE_GATE_PASS'
Write-Host 'No browser launched. No booking submitted. RC and main untouched.'
