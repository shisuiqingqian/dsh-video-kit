# dsh-video-kit uninstaller
# 从 DeepSeek Harness 里移除 dsh-video-kit（保留 ~/.dsh/toolkits/video-kit 里的模型与视频）。
#
#   .\uninstall.ps1                    # 卸载挂载 + 文件
#   .\uninstall.ps1 -KeepFiles         # 只摘挂载，文件留着
#   .\uninstall.ps1 -PurgeData         # 连模型/视频数据一起删（省 ~230 MB）

[CmdletBinding()]
param(
  [string]$DshHome = (Join-Path $env:USERPROFILE '.dsh'),
  [string]$Profile = 'desktop',
  [switch]$KeepFiles,
  [switch]$PurgeData
)

$ErrorActionPreference = 'Stop'
function Say($m, $c = 'Gray') { Write-Host $m -ForegroundColor $c }

$pluginsDir = Join-Path $DshHome 'local-plugins'
$target = Join-Path $pluginsDir 'dsh-video-kit'
$profileDir = Join-Path $DshHome "profiles\$Profile"
$profilePkg = Join-Path $profileDir 'package.json'
$profilePatch = Join-Path $profileDir 'cordis.patch.yml'
$nodeModules = Join-Path $profileDir 'node_modules\dsh-video-kit'
$data = Join-Path $DshHome 'toolkits\video-kit'

Say "`n=== dsh-video-kit uninstaller ===" Cyan

# 1. 摘挂载
if (Test-Path $profilePatch) {
  $bak = "$profilePatch.bak-video-kit-uninstall"
  Copy-Item $profilePatch $bak
  $pt = Get-Content $profilePatch -Raw -Encoding UTF8
  $pattern = '(?ms)\r?\n?# 本地插件：视频读取工具[^\r\n]*\r?\n- insert:\r?\n\s+- id: tool-video-kit\r?\n\s+name: [^\r\n]+'
  $new = [regex]::Replace($pt, $pattern, '')
  if ($new -ne $pt) {
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($profilePatch, $new, $enc)
    Say "[1/3] 已从 $profilePatch 摘除挂载块（备份 $bak）" Green
  } else {
    Say "[1/3] 补丁中未找到挂载块，跳过" DarkGray
  }
}

# 2. 移除依赖声明
if (Test-Path $profilePkg) {
  $obj = Get-Content $profilePkg -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($obj.dependencies -and $obj.dependencies.'dsh-video-kit') {
    $obj.dependencies.PSObject.Properties.Remove('dsh-video-kit')
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($profilePkg, ($obj | ConvertTo-Json -Depth 12), $enc)
    Say "[2/3] 已移除 package.json 里的依赖声明" Green
  } else { Say "[2/3] 依赖声明不存在，跳过" DarkGray }
}

# 3. 删文件
if (-not $KeepFiles) {
  foreach ($p in @($target, $nodeModules)) {
    if (Test-Path $p) { Remove-Item $p -Recurse -Force; Say "[3/3] 已删除 $p" Green }
  }
} else { Say "[3/3] -KeepFiles：保留文件" DarkGray }

if ($PurgeData -and (Test-Path $data)) {
  $size = [math]::Round(((Get-ChildItem $data -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 1)
  Remove-Item $data -Recurse -Force
  Say "已删除数据目录 $data（释放约 $size MB）" Yellow
} elseif (Test-Path $data) {
  Say "数据目录保留：$data（用 -PurgeData 可一并删除）" DarkGray
}

Say "`n完成。重启 DeepSeek Harness 后生效。" Green
