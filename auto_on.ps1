# 자동 게시 예약 등록 (놓친 회차는 PC를 켜면 바로 실행, 절전 중이면 깨워서 실행)
$ErrorActionPreference = 'Stop'
$dir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$name = Split-Path -Leaf $dir
$times = @('09:00','13:00','20:00')
$envFile = Join-Path $dir '.env'
if (Test-Path $envFile) {
  foreach ($line in Get-Content $envFile -Encoding UTF8) {
    if ($line -match '^\s*POST_TIMES\s*=\s*(.+)$') { $times = $Matches[1].Trim().Split(' ', [StringSplitOptions]::RemoveEmptyEntries) }
  }
}
Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -like "CoupangAutoPost_${name}_*" } |
  ForEach-Object { Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false }

$run = Join-Path $dir 'run.bat'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Write-Host "[$name] 자동 게시 예약:"
foreach ($t in $times) {
  $action  = New-ScheduledTaskAction -Execute $run -WorkingDirectory $dir
  $trigger = New-ScheduledTaskTrigger -Daily -At $t
  Register-ScheduledTask -TaskName ("CoupangAutoPost_${name}_" + $t.Replace(':','')) -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
  Write-Host "  - 매일 $t"
}
$action  = New-ScheduledTaskAction -Execute $run -Argument 'refresh' -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '08:00'
Register-ScheduledTask -TaskName "CoupangAutoPost_${name}_refresh" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "  - 토큰 자동 연장: 매주 일요일 08:00"
Write-Host ""
Write-Host "등록된 예약:"
Get-ScheduledTask | Where-Object { $_.TaskName -like "CoupangAutoPost_${name}_*" } | ForEach-Object {
  $i = $_ | Get-ScheduledTaskInfo
  Write-Host ("  {0}  다음 실행: {1}" -f $_.TaskName, $i.NextRunTime)
}
Write-Host ""
Write-Host "자동 게시가 켜졌습니다. PC가 꺼져 있어 놓친 회차는 PC를 켜면 바로 올라갑니다."
