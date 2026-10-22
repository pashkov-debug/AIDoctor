param(
    [string]$BaseUrl = "http://127.0.0.1:8000"
)
$ErrorActionPreference = "Stop"

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "UI-1 smoke FAIL: $Message" }
}

$index = Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/app"
Assert-True ($index.StatusCode -eq 200) "/app не отвечает 200"
Assert-True ($index.Content.Contains('id="login-form"')) "Нет формы входа"
Assert-True ($index.Headers["Cache-Control"] -match "no-store") "Нет no-store"

foreach ($path in @("/app/assets/style.css", "/app/assets/app.js")) {
    $res = Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl$path"
    Assert-True ($res.StatusCode -eq 200) "$path не отвечает 200"
}

foreach ($path in @("/api/v1/doctors/me/settings", "/api/v1/doctors/me/doctor-context")) {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl$path" | Out-Null
        throw "UI-1 smoke FAIL: неавторизованный $path доступен"
    } catch {
        $status = [int]$_.Exception.Response.StatusCode
        Assert-True ($status -eq 401) "Ожидался 401 для $path; фактически $status"
    }
}

Write-Host "UI-1 smoke OK: HTML, статические файлы, no-store, анонимный доступ 401." -ForegroundColor Green
