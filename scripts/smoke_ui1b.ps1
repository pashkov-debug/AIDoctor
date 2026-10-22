param([string]$BaseUrl = "http://127.0.0.1:8000")
$ErrorActionPreference = "Stop"

$page = Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/app"
if ($page.StatusCode -ne 200 -or -not $page.Content.Contains('id="patient-view"')) {
    throw "UI-1B: карточка пациента не найдена в интерфейсе."
}
if ($page.Headers["Cache-Control"] -notmatch "no-store") {
    throw "UI-1B: HTML должен иметь no-store."
}
foreach ($path in @("/app/assets/app.js", "/app/assets/style.css")) {
    $response = Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl$path"
    if ($response.StatusCode -ne 200) { throw "UI-1B: ошибка $path" }
}
try {
    Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/api/v1/patients/me/portal" | Out-Null
    throw "UI-1B: неавторизованная карточка оказалась доступна"
}
catch {
    if ([int]$_.Exception.Response.StatusCode -ne 401) {
        throw "UI-1B: ожидался 401 на неавторизованный доступ."
    }
}
Write-Host "UI-1B smoke OK: HTML, ресурсы, no-store, анонимный доступ 401." -ForegroundColor Green
