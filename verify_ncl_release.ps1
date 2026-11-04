# NCL OPEN LAB release candidate preflight. Read-only: NO browser / booking / HTTP.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$expectedBranch = 'feat/ncl-openlab-booking'
$branch = (& git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Git branch check failed' }
if ($branch -ne $expectedBranch) {
    throw "Wrong branch '$branch'. Expected '$expectedBranch'. Main is intentionally untouched."
}

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Missing .venv Python: $python"
}

Write-Host 'NCL RELEASE CHECK: compiling local source (no browser, no booking)...'
$sourceFiles = @(
    'src\ncl_openlab_autobook.py',
    'src\ncl_openlab_picker.py',
    'src\ncl_openlab_picker_model.py',
    'src\ncl_openlab_rooms.py',
    'src\ncl_openlab_diag.py',
    'src\ncl_openlab_inventory.py',
    'src\ncl_openlab_schedule.py',
    'src\ncl_openlab_browser.py',
    'src\ncl_openlab_control.py',
    'src\ncl_browser_lifecycle_smoke.py'
)
& $python -m py_compile @sourceFiles
if ($LASTEXITCODE -ne 0) { throw 'PYTHON_COMPILE_FAILED' }

Write-Host 'NCL RELEASE CHECK: running offline unit tests...'
& $python -m unittest discover -s tests -p 'test_ncl_openlab_*.py' -q
if ($LASTEXITCODE -ne 0) { throw 'NCL_OFFLINE_TESTS_FAILED' }

Write-Host 'NCL RELEASE CHECK: offline report (skipped tests are NOT_VERIFIED, not PASS)...'
& $python tests\run_ncl_offline_report.py --out-dir ncl_reports
if ($LASTEXITCODE -ne 0) { throw 'NCL_OFFLINE_REPORT_FAILED' }

Write-Host 'NCL_RELEASE_GATE_PASS'
Write-Host 'Branch: feat/ncl-openlab-booking. Main unchanged by this script.'
Write-Host 'No live booking occurred. Open launch_ncl_picker.cmd separately to book.'
