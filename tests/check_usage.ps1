# 竹喧的资源占用实测（纯英文脚本，避免中文编码问题）
$ErrorActionPreference = "SilentlyContinue"

Write-Output "===== 内存（RAM） ====="

$appPid = (Get-NetTCPConnection -LocalPort 8765 -State Listen | Select-Object -First 1).OwningProcess
if ($appPid) {
    $p = Get-Process -Id $appPid
    Write-Output ("竹喧后台服务（python）: {0:N1} MB" -f ($p.WorkingSet64 / 1MB))
} else {
    Write-Output "竹喧服务没在跑"
}

$edge = Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" |
        Where-Object { $_.CommandLine -like '*edge-profile*' }
$edgeSum = 0
$n = 0
foreach ($e in $edge) {
    $proc = Get-Process -Id $e.ProcessId
    if ($proc) { $edgeSum += $proc.WorkingSet64; $n++ }
}
Write-Output ("竹喧窗口（Edge，{0} 个子进程）: {1:N1} MB" -f $n, ($edgeSum / 1MB))

$all = Get-Process -Name msedge
$allSum = 0
foreach ($a in $all) { $allSum += $a.WorkingSet64 }
Write-Output ("（对比）你日常所有 Edge 窗口加起来: {0:N0} MB / {1} 个进程" -f ($allSum / 1MB), $all.Count)

Write-Output ""
Write-Output "===== 磁盘 ====="
foreach ($d in @("D:\kk\WordApp\data\edge-profile", "D:\kk\WordApp\data\backups", "D:\kk\WordApp\data", "D:\kk\WordApp")) {
    $files = Get-ChildItem $d -Recurse -Force -File
    $sum = ($files | Measure-Object -Property Length -Sum).Sum
    Write-Output ("{0,-42} {1,8:N1} MB  ({2} 个文件)" -f $d, ($sum / 1MB), $files.Count)
}

Write-Output ""
Write-Output "===== 关键文件 ====="
foreach ($f in @("D:\kk\WordApp\data\words.db", "D:\kk\WordApp\竹喧.exe")) {
    $i = Get-Item $f
    Write-Output ("{0,-42} {1,8:N1} MB  最后修改 {2}" -f $f, ($i.Length / 1MB), $i.LastWriteTime)
}

Write-Output ""
Write-Output "===== edge-profile 里占地方最多的是什么 ====="
Get-ChildItem "D:\kk\WordApp\data\edge-profile" -Recurse -Force -File |
    Sort-Object Length -Descending |
    Select-Object -First 6 |
    ForEach-Object { Write-Output ("{0,8:N1} MB  {1}" -f ($_.Length / 1MB), $_.FullName.Replace("D:\kk\WordApp\data\edge-profile\", "")) }
