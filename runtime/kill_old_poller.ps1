# 杀掉旧的 wait_broadcast_evidence 轮询进程（脚本文件方式避免 shell 转义）
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*wait_broadcast_evidence*' }
foreach ($p in $procs) {
    Write-Host ("KILL " + $p.ProcessId)
    Stop-Process -Id $p.ProcessId -Force
}
Write-Host "OLD_POLLER_CLEANUP_DONE"
