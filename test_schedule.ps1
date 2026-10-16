# 5분 뒤 한 번만 자동 게시 (예약이 실제로 도는지 확인용)
$ErrorActionPreference = 'Stop'
$dir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$name = Split-Path -Leaf $dir
$at   = (Get-Date).AddMinutes(5)
$run  = Join-Path $dir 'run.bat'
$action   = New-ScheduledTaskAction -Execute $run -WorkingDirectory $dir
$trigger  = New-ScheduledTaskTrigger -Once -At $at
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName "CoupangAutoPost_${name}_test" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host ("{0:HH:mm}에 한 번 자동 게시하도록 예약했습니다. 이 창은 닫아도 됩니다." -f $at)
Write-Host "결과는 logs\task.log 에 남습니다."
