$ErrorActionPreference = "Stop"

$Url = "http://127.0.0.1:8000/api/v1/health"

Write-Host "Проверка backend: $Url"

try {
    $response = Invoke-RestMethod `
        -Uri $Url `
        -Method Get `
        -TimeoutSec 5

    if ($response.status -ne "ok") {
        throw "Backend вернул неожиданный status: $($response.status)"
    }

    Write-Host "OK"
    Write-Host "Service: $($response.service)"
    Write-Host "Environment: $($response.environment)"
}
catch {
    Write-Error "Smoke-test не пройден: $($_.Exception.Message)"
    exit 1
}