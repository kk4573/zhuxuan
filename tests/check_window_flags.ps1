# 确认竹喧窗口真的带上了禁自动填充的参数
$ErrorActionPreference = "SilentlyContinue"

$procs = Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" |
         Where-Object { $_.CommandLine -like '*edge-profile*' }

Write-Output ("竹喧窗口进程数: {0}" -f @($procs).Count)

$main = $procs | Where-Object { $_.CommandLine -like '*--app=*' } | Select-Object -First 1
if (-not $main) { $main = $procs | Select-Object -First 1 }

if ($main) {
    $cl = $main.CommandLine
    Write-Output ""
    Write-Output "===== 传给 Edge 的参数检查 ====="
    if ($cl -like '*--disable-features=*') {
        $m = [regex]::Match($cl, '--disable-features=([^" ]+)')
        Write-Output "  [ok] --disable-features 已带上，禁用的开关："
        foreach ($f in $m.Groups[1].Value -split ',') {
            Write-Output ("        · " + $f)
        }
    } else {
        Write-Output "  [FAIL] 没找到 --disable-features"
    }
    if ($cl -like '*--disable-save-password-bubble*') {
        Write-Output "  [ok] --disable-save-password-bubble 已带上"
    } else {
        Write-Output "  [FAIL] 没有 --disable-save-password-bubble"
    }
    if ($cl -like '*--user-data-dir=*') {
        $d = [regex]::Match($cl, '--user-data-dir=([^" ]+)').Groups[1].Value
        Write-Output ("  [ok] --user-data-dir = " + $d)
    }
    if ($cl -like '*--app=http*') {
        Write-Output "  [ok] 独立窗口模式（--app）正常"
    }
} else {
    Write-Output "  [FAIL] 没找到竹喧窗口进程"
}
