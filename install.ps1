# dsh-video-kit installer
# 把 dsh-video-kit 装进 DeepSeek Harness（写入 profile 的补丁层），可重复执行。
#
#   .\install.ps1                  # 默认装到 %USERPROFILE%\.dsh\profiles\desktop
#   .\install.ps1 -Profile 其他名字
#   .\install.ps1 -NoPatch         # 只铺文件，不动配置文件（手工挂载用）
#   .\install.ps1 -WhatIfOnly      # 只打印将要做的事
#
# 卸载：.\uninstall.ps1

[CmdletBinding()]
param(
  [string]$DshHome = (Join-Path $env:USERPROFILE '.dsh'),
  [string]$Profile = 'desktop',
  [switch]$NoPatch,
  [switch]$WhatIfOnly
)

$ErrorActionPreference = 'Stop'
function Say($m, $c = 'Gray') { Write-Host $m -ForegroundColor $c }

# Windows PowerShell 5.1 的 Set-Content -Encoding UTF8 会写 **带 BOM** 的 UTF-8，
# 而 DSH 用 JSON.parse 读 profile manifest —— BOM 会让它直接崩在启动阶段
# （报错：Unexpected token '\uFEFF', "{... is not valid JSON）。
# 所有配置文件一律走下面这个函数，字节级保证无 BOM。
function Write-Utf8NoBom([string]$Path, [string]$Text) {
  $enc = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($Path, $Text, $enc)
}
function Append-Utf8NoBom([string]$Path, [string]$Text) {
  $existing = ''
  if (Test-Path $Path) { $existing = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8) }
  if ($existing.Length -gt 0 -and -not $existing.EndsWith("`n")) { $existing += "`n" }
  Write-Utf8NoBom $Path ($existing + $Text)
}
function Assert-NoBom([string]$Path) {
  if (-not (Test-Path $Path)) { return $true }
  $b = [System.IO.File]::ReadAllBytes($Path)
  if ($b.Length -ge 3 -and $b[0] -eq 239 -and $b[1] -eq 187 -and $b[2] -eq 191) {
    throw "写入后仍带 BOM：$Path（必须无 BOM，否则 DSH 启动会失败）"
  }
  return $true
}

$pkgRoot = $PSScriptRoot
$pluginsDir = Join-Path $DshHome 'local-plugins'
$target = Join-Path $pluginsDir 'dsh-video-kit'
$profileDir = Join-Path $DshHome "profiles\$Profile"
$profilePkg = Join-Path $profileDir 'package.json'
$profilePatch = Join-Path $profileDir 'cordis.patch.yml'
$nodeModules = Join-Path $profileDir 'node_modules\dsh-video-kit'

Say "`n=== dsh-video-kit installer ===" Cyan
Say "包目录 : $pkgRoot"
Say "DSH 根 : $DshHome"
Say "Profile: $profileDir"

if (-not (Test-Path $profileDir)) {
  throw "找不到 profile 目录：$profileDir`n请用 -Profile 指定正确的 profile 名。"
}
if (-not (Test-Path (Join-Path $pkgRoot 'index.js'))) {
  throw "包不完整：$pkgRoot 下缺少 index.js（请解压后在本目录内运行脚本）。"
}
if ($WhatIfOnly) { Say "`n[试运行] 不做任何修改。" Yellow; return }

# ---------------------------------------------------------------- 1. 铺文件
Say "`n[1/6] 铺文件到 local-plugins" Cyan
New-Item -ItemType Directory -Force -Path $pluginsDir | Out-Null
if (Test-Path $target) {
  $keep = Join-Path $pluginsDir "dsh-video-kit.bak-$(Get-Date -f yyyyMMdd-HHmmss)"
  Move-Item $target $keep
  Say "  旧版本已备份 -> $keep" DarkGray
}
Copy-Item $pkgRoot $target -Recurse
Say "  -> $target" Green

# ---------------------------------------------------------------- 2. 同步到 profile/node_modules
Say "`n[2/6] 同步到 profile/node_modules" Cyan
New-Item -ItemType Directory -Force -Path (Split-Path $nodeModules) | Out-Null
if (Test-Path $nodeModules) { Remove-Item $nodeModules -Recurse -Force }
Copy-Item $target $nodeModules -Recurse
Say "  -> $nodeModules" Green

# ---------------------------------------------------------------- 3. 依赖声明
Say "`n[3/6] 登记依赖" Cyan
if (Test-Path $profilePkg) {
  $raw = Get-Content $profilePkg -Raw -Encoding UTF8
  $obj = $raw | ConvertFrom-Json
  if (-not $obj.dependencies) {
    $obj | Add-Member -NotePropertyName dependencies -NotePropertyValue ([pscustomobject]@{}) -Force
  }
  $rel = '../../local-plugins/dsh-video-kit'
  $existing = $obj.dependencies.'dsh-video-kit'
  if ($existing -ne "file:$rel") {
    if ($existing) { $obj.dependencies.'dsh-video-kit' = "file:$rel" }
    else { $obj.dependencies | Add-Member -NotePropertyName 'dsh-video-kit' -NotePropertyValue "file:$rel" -Force }
    Say "  dependencies['dsh-video-kit'] = file:$rel" Green
  } else { Say "  依赖已存在，跳过" DarkGray }

  # 关键：从 bundles 里移除，改由 profile 补丁层显式挂载，避免双挂导致重复注册
  if ($obj.dsh -and $obj.dsh.profile -and $obj.dsh.profile.bundles) {
    $before = @($obj.dsh.profile.bundles).Count
    $kept = @($obj.dsh.profile.bundles | Where-Object { $_ -ne 'dsh-video-kit' })
    if ($kept.Count -ne $before) {
      $obj.dsh.profile.bundles = $kept
      Say "  已从 dsh.profile.bundles 移除 dsh-video-kit（改由补丁层挂载）" Yellow
    }
  }
  # 关键：一律无 BOM 写回，并立刻验字节
  Write-Utf8NoBom $profilePkg ($obj | ConvertTo-Json -Depth 12)
  Assert-NoBom $profilePkg | Out-Null
} else {
  Say "  未找到 $profilePkg，跳过依赖登记（可手工加 file: 依赖）" Yellow
}

# ---------------------------------------------------------------- 4. 挂载
if (-not $NoPatch) {
  Say "`n[4/6] 写入 profile 补丁层" Cyan
  if (-not (Test-Path $profilePatch)) { New-Item -ItemType File -Path $profilePatch | Out-Null }
  $bak = "$profilePatch.bak-video-kit"
  if (-not (Test-Path $bak)) { Copy-Item $profilePatch $bak; Say "  备份 -> $bak" DarkGray }
  $pt = Get-Content $profilePatch -Raw -Encoding UTF8
  if ($pt -match 'tool-video-kit') {
    Say "  补丁已存在，跳过" DarkGray
  } else {
    $block = "`n# 本地插件：视频读取工具（video_read），进程级挂载`n- insert:`n    - id: tool-video-kit`n      name: `"dsh-video-kit`"`n"
    Append-Utf8NoBom $profilePatch $block
    Say "  已追加挂载块" Green
  }
} else {
  Say "`n[4/6] 跳过挂载（-NoPatch）" Yellow
}

# ---------------------------------------------------------------- 5. 体检
Say "`n[5/6] 配置字节体检" Cyan
Assert-NoBom $profilePkg | Out-Null
Assert-NoBom $profilePatch | Out-Null
Say "  package.json / cordis.patch.yml 均无 BOM" Green

# 用 DSH 同款解析器验证（PowerShell 的 ConvertFrom-Json 容忍 BOM，会漏掉这次的事故）
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
  $check = & node -e "try{JSON.parse(require('fs').readFileSync(process.argv[1],'utf8'));console.log('OK')}catch(e){console.log('FAIL '+e.message)}" $profilePkg
  if ($check -notmatch '^OK') { throw "profile package.json 无法被 JSON.parse 解析：$check" }
  Say "  JSON.parse 校验通过" Green
} else {
  Say "  未找到 node，跳过 JSON.parse 校验（已做 BOM 字节检查）" Yellow
}

# ---------------------------------------------------------------- 6. 依赖
Say "`n[6/6] 运行时依赖体检" Cyan
$setup = Join-Path $target 'bin\setup.py'
if (Test-Path $setup) {
  try {
    & python $setup --check 2>&1 | ForEach-Object { "  $_" }
  } catch {
    Say "  体检脚本执行失败（不影响安装）：$($_.Exception.Message)" Yellow
  }
} else { Say "  缺少 bin\setup.py，跳过" Yellow }

# ---------------------------------------------------------------- 结论
Say "`n=== 安装完成 ===" Green
Say "接下来必须做两件事，否则看不到工具："
Say "  1) 完全退出并重新打开 DeepSeek Harness（插件在进程启动时加载）"
Say "  2) 新开一个会话（已有会话的工具表是冻结的，不会热更新）"
Say ""
Say "验证：在新会话里问「用 video_read 读 <视频路径>」"
Say "首次调用会自动下载依赖与 ASR 模型（约 290 MB），或提前跑："
Say "  python `"$setup`""
Say ""
Say "回滚配置：$profilePatch.bak-video-kit" DarkGray
