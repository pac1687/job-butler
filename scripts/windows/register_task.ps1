# Phase 4.1: Windows Task Scheduler registration script for Job Butler Nightly Worker
param(
    [string]$ProjectDir = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string]$TaskName = "JobButlerNightlyWorker"
)

$Action = New-ScheduledTaskAction `
    -Execute "docker" `
    -Argument "compose run --rm worker" `
    -WorkingDirectory $ProjectDir

$Trigger = New-ScheduledTaskTrigger -Daily -At 2:00AM

$Settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Runs the Job Butler Docker worker nightly at 02:00 AM with distributed lease coordination." `
    -Force

Write-Host "Registered scheduled task '$TaskName' in $ProjectDir for 02:00 AM daily."

