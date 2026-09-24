# Reproduce the whole experiment. Assumes Python 3.12+ and a Google AI Studio key pool.
# Override the pool with:  $env:GOOGLE_AI_KEYS_FILE = "C:\path\to\keys.txt"

$models = @("gemini-2.5-flash-lite", "gemini-3.5-flash-lite")

foreach ($m in $models) {
    Write-Host "=== extract: $m ===" -ForegroundColor Cyan
    python llm_extract.py --model $m
    if (-not $?) { Write-Host "extraction failed for $m" -ForegroundColor Red; continue }

    Write-Host "=== compare: $m ===" -ForegroundColor Cyan
    python compare.py --llm "out/llm_ir.$m.json"
}

Write-Host "`nReports:" -ForegroundColor Green
Get-ChildItem out/*.report.md | ForEach-Object { Write-Host "  $($_.FullName)" }
