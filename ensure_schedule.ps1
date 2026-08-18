# Self-heal: ensure the 'XHS Weekly Report' scheduled task exists (recreate if missing)
$taskName = 'XHS Weekly Report'
$proj = 'C:\Users\DanielHau\Documents\New prototype'
$py = 'C:\Users\DanielHau\AppData\Local\Programs\Python\Python314\python.exe'
$log = Join-Path $proj 'data\schedule_selfheal.log'

# 讀取應用程式寫的排程設定（預設：週五 09:00）
$cfgDay = 'Friday'
$cfgTime = '09:00'
$cfgEnabled = $true
$cfgPath = Join-Path $proj 'data\schedule_config.json'
if (Test-Path $cfgPath) {
    try {
        $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
        if ($cfg.enabled -eq $false) { $cfgEnabled = $false }
        if ($cfg.day) { $cfgDay = [string]$cfg.day }
        if ($null -ne $cfg.hour) { $cfgTime = ('{0:00}:{1:00}' -f [int]$cfg.hour, [int]$cfg.minute) }
    } catch {}
}
if (-not $cfgEnabled) { exit 0 }

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Add-Content -Path $log -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') task already exists" -ErrorAction SilentlyContinue
} else {
    try {
        $action = New-ScheduledTaskAction -Execute $py -Argument 'run_weekly.py' -WorkingDirectory $proj
        $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $cfgDay -At $cfgTime
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3)
        $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
        Add-Content -Path $log -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') task recreated" -ErrorAction SilentlyContinue
    } catch {
        Add-Content -Path $log -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') recreate failed: $_" -ErrorAction SilentlyContinue
    }
}

# 2) Catch-up: run the report if the latest Friday run is missing
try {
    & $py (Join-Path $proj 'run_if_missed.py') 2>&1 | Add-Content -Path $log
} catch {
    Add-Content -Path $log -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') catch-up failed: $_" -ErrorAction SilentlyContinue
}
