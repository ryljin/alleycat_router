$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Testing /optimize..." -ForegroundColor Cyan
Write-Host ""

$response = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/optimize" `
  -ContentType "application/json" `
  -Body (Get-Content sample_request.json -Raw)

Write-Host "Optimized order:" -ForegroundColor Green
$response.optimized_order_labels | ForEach-Object {
    Write-Host "  $_"
}

Write-Host ""
Write-Host "Total duration seconds:" -ForegroundColor Green
$response.total_duration_seconds

Write-Host ""
Write-Host "Total distance meters:" -ForegroundColor Green
$response.total_distance_meters

Write-Host ""
Write-Host "Method:" -ForegroundColor Green
$response.method

Write-Host ""
Write-Host "Legs:" -ForegroundColor Green
$response.legs | Format-Table from_label, to_label, duration_seconds, distance_meters

$response | ConvertTo-Json -Depth 20 | Out-File optimized_response.json

Write-Host ""
Write-Host "Saved full response to optimized_response.json" -ForegroundColor Yellow
Write-Host ""