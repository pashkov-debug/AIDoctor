param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$DoctorUser = "doctor_ui1",
    [string]$PatientUser = "patient_ui1",
    [string]$AdminUser = "admin_ui1"
)
$ErrorActionPreference = "Stop"

# Только локальная база разработки и только синтетические карточки.
if ($BaseUrl -notmatch '^http://(127\.0\.0\.1|localhost):[0-9]+$') {
    throw "Разрешён только HTTP loopback с явным портом."
}
$BaseUrl = $BaseUrl.TrimEnd('/')

function Get-AuthHeaders([string]$Username) {
    $password = Read-Host "Пароль учётной записи $Username" -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
    try {
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
        $body = @{ username = $Username; password = $plain } | ConvertTo-Json -Compress
        $token = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/auth/login" `
            -ContentType "application/json" -Body $body
        return @{ Authorization = "Bearer $($token.access_token)" }
    }
    finally {
        $plain = $null
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

# Все три роли проверяем ДО создания карточки, чтобы не создавать orphan при ошибке входа.
$patientHeaders = Get-AuthHeaders $PatientUser
$doctorHeaders = Get-AuthHeaders $DoctorUser
$adminHeaders = Get-AuthHeaders $AdminUser

$patientUserInfo = Invoke-RestMethod -Uri "$BaseUrl/api/v1/auth/me" -Headers $patientHeaders
if ($patientUserInfo.role -ne "patient") { throw "Пользователь $PatientUser не пациент." }
$doctorInfo = Invoke-RestMethod -Uri "$BaseUrl/api/v1/auth/me" -Headers $doctorHeaders
if ($doctorInfo.role -ne "doctor") { throw "Пользователь $DoctorUser не врач." }
$adminInfo = Invoke-RestMethod -Uri "$BaseUrl/api/v1/auth/me" -Headers $adminHeaders
if ($adminInfo.role -ne "admin") { throw "Пользователь $AdminUser не администратор." }

try {
    $existing = Invoke-RestMethod -Uri "$BaseUrl/api/v1/patients/me/portal" `
        -Headers $patientHeaders
    Write-Host "Карточка уже привязана: $($existing.patient_id). Ничего не изменено."
    exit 0
}
catch {
    $statusCode = [int]$_.Exception.Response.StatusCode
    if ($statusCode -ne 404) { throw }
}

$patientBody = @{
    alias = "Синтетический пациент UI-1B"
    demographics = @{ synthetic = $true }
} | ConvertTo-Json -Depth 4 -Compress
$created = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/patients" `
    -Headers $doctorHeaders -ContentType "application/json" -Body $patientBody

try {
    $linkBody = @{
        patient_id = $created.id
        user_id = $patientUserInfo.id
    } | ConvertTo-Json -Compress
    Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/access/patient-account" `
        -Headers $adminHeaders -ContentType "application/json" -Body $linkBody | Out-Null
}
catch {
    Write-Warning "Карточка $($created.id) создана, но привязка не завершена. Повторно seed без проверки не выполнять."
    throw
}
$confirmed = Invoke-RestMethod -Uri "$BaseUrl/api/v1/patients/me/portal" -Headers $patientHeaders
if ($confirmed.patient_id -ne $created.id) {
    throw "После привязки портал вернул другой идентификатор пациента."
}
Write-Host "UI-1B: синтетическая карточка $($confirmed.patient_id) привязана к $PatientUser." -ForegroundColor Green
