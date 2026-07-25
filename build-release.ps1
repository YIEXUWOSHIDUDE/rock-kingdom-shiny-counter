param(
    [string]$ModelDirectory = "$env:APPDATA\RockKingdomShinyCounter\ocr-models",
    [string]$VenvDirectory = "release\.venv-cuda130",
    [string]$WheelhouseDirectory = "release\wheelhouse-win-py313",
    [switch]$ReuseEnvironment,
    [switch]$SkipTests,
    [switch]$SkipLocalGpuProbe
)

$ErrorActionPreference = "Stop"
$Root = [IO.Path]::GetFullPath($PSScriptRoot)
Set-Location $Root
$Version = (Get-Content -LiteralPath (Join-Path $Root "VERSION") -Raw).Trim()
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "VERSION 格式无效：$Version"
}

function Invoke-Checked {
    param(
        [string]$Description,
        [scriptblock]$Command
    )
    Write-Host "==> $Description"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description 失败，退出码 $LASTEXITCODE"
    }
}

function Reset-ProjectDirectory {
    param([string]$Path)
    $FullPath = [IO.Path]::GetFullPath($Path)
    $Prefix = $Root.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $FullPath.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝清理工作区外目录：$FullPath"
    }
    if (Test-Path -LiteralPath $FullPath) {
        Remove-Item -LiteralPath $FullPath -Recurse -Force
    }
    New-Item -ItemType Directory -Path $FullPath | Out-Null
    return $FullPath
}

$ModelDirectory = [IO.Path]::GetFullPath($ModelDirectory)
foreach ($Name in @("craft_mlt_25k.pth", "zh_sim_g2.pth")) {
    if (-not (Test-Path -LiteralPath (Join-Path $ModelDirectory $Name) -PathType Leaf)) {
        throw "缺少离线 OCR 模型：$(Join-Path $ModelDirectory $Name)"
    }
}

$VenvDirectory = [IO.Path]::GetFullPath((Join-Path $Root $VenvDirectory))
$WheelhouseDirectory = [IO.Path]::GetFullPath(
    (Join-Path $Root $WheelhouseDirectory)
)
$WheelhouseManifest = Join-Path $WheelhouseDirectory "MANIFEST.sha256.json"
$Python = Join-Path $VenvDirectory "Scripts\python.exe"
if (-not $ReuseEnvironment) {
    $WheelhouseReady = $false
    if (Test-Path -LiteralPath $WheelhouseManifest -PathType Leaf) {
        py -3.13 -m build_tools.package_installer `
            verify `
            $WheelhouseDirectory `
            $WheelhouseManifest
        $WheelhouseReady = $LASTEXITCODE -eq 0
        if (-not $WheelhouseReady) {
            Write-Warning "wheelhouse 清单校验失败，将重新下载全部锁定 wheel。"
            $WheelhouseDirectory = Reset-ProjectDirectory $WheelhouseDirectory
            $WheelhouseManifest = Join-Path $WheelhouseDirectory "MANIFEST.sha256.json"
        }
    }
    if (-not $WheelhouseReady) {
        New-Item -ItemType Directory -Path $WheelhouseDirectory -Force | Out-Null
        Invoke-Checked "下载锁定的 Windows Python 3.13 wheelhouse" {
            py -3.13 -m pip download `
                --dest $WheelhouseDirectory `
                --only-binary=:all: `
                --extra-index-url https://download.pytorch.org/whl/cu130 `
                -r requirements-lock-win-py313.txt
        }
        Invoke-Checked "生成 wheelhouse SHA-256 清单" {
            py -3.13 -m build_tools.package_installer `
                manifest `
                $WheelhouseDirectory `
                $WheelhouseManifest
        }
    }
    Invoke-Checked "复核 wheelhouse 文件集合与 SHA-256" {
        py -3.13 -m build_tools.package_installer `
            verify `
            $WheelhouseDirectory `
            $WheelhouseManifest
    }
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        Invoke-Checked "创建 Python 3.13 发布环境" {
            py -3.13 -m venv $VenvDirectory
        }
    }
    Invoke-Checked "仅从本地 wheelhouse 安装全部锁定依赖" {
        & $Python -m pip install `
            --no-index `
            --find-links $WheelhouseDirectory `
            --upgrade `
            -r requirements-lock-win-py313.txt
    }
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "发布 Python 不存在：$Python"
}

$BuildRoot = Reset-ProjectDirectory (Join-Path $Root "release\build")
$StagingRoot = Reset-ProjectDirectory (Join-Path $Root "release\staging")
$OutputRoot = Reset-ProjectDirectory (Join-Path $Root "release\out")
$BuildEnvironment = Join-Path $OutputRoot "build-environment.json"

Invoke-Checked "验证 CUDA 13 wheel、目标架构与模型哈希" {
    & $Python -m build_tools.release_validation `
        --model-dir $ModelDirectory `
        --output $BuildEnvironment
}

if (-not $SkipTests) {
    Invoke-Checked "运行 Python 测试" {
        & $Python -m unittest discover -s tests -v
    }
}

$ProbeImage = Join-Path $BuildRoot "ocr-probe.png"
Invoke-Checked "生成固定中文 OCR 探针图片" {
    & $Python -m build_tools.create_ocr_probe `
        --font "$env:WINDIR\Fonts\msyh.ttc" `
        --output $ProbeImage
}
$env:RKSC_MODEL_DIR = $ModelDirectory
$env:RKSC_PROBE_IMAGE = $ProbeImage
Invoke-Checked "构建 one-folder GPU 应用" {
    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --workpath $BuildRoot `
        --distpath $StagingRoot `
        packaging\RockKingdomShinyCounter.spec
}

$AppDirectory = Join-Path $StagingRoot "RockKingdomShinyCounter"
$AppExecutable = Join-Path $AppDirectory "RockKingdomShinyCounter.exe"
if (-not (Test-Path -LiteralPath $AppExecutable -PathType Leaf)) {
    throw "PyInstaller 未生成主程序：$AppExecutable"
}
Copy-Item -LiteralPath (Join-Path $Root "README.md") -Destination (Join-Path $AppDirectory "使用说明.md")

$PackageReport = Join-Path $OutputRoot "package-probe.json"
Invoke-Checked "验证冻结包导入边界和离线资源" {
    & $Python -m build_tools.run_frozen_probe `
        $AppExecutable `
        package `
        $PackageReport
}

$Csc = (
    Get-ChildItem -Path "$env:WINDIR\Microsoft.NET\Framework64" -Filter csc.exe -Recurse |
        Sort-Object FullName -Descending |
        Select-Object -First 1
).FullName
if (-not $Csc) {
    throw "找不到 .NET Framework C# 编译器 csc.exe"
}

Invoke-Checked "编译卸载程序" {
    & $Csc `
        /nologo `
        /target:winexe `
        "/out:$(Join-Path $AppDirectory 'Uninstall.exe')" `
        /r:System.Windows.Forms.dll `
        packaging\Uninstaller.cs
}

$AppManifest = Join-Path $AppDirectory "MANIFEST.sha256.json"
Invoke-Checked "生成应用文件哈希清单" {
    & $Python -m build_tools.package_installer manifest $AppDirectory $AppManifest
}

$RuntimeReport = Join-Path $OutputRoot "runtime-probe.json"
$ProbeStatus = "skipped"
if (-not $SkipLocalGpuProbe) {
    Invoke-Checked "用冻结程序执行 CUDA 张量与 EasyOCR 真实推理" {
        & $Python -m build_tools.run_frozen_probe `
            $AppExecutable `
            runtime `
            $RuntimeReport
    }
    $ProbeStatus = "passed"
}

$Payload = Join-Path $BuildRoot "payload-v$Version.zip"
Invoke-Checked "生成确定性离线载荷" {
    & $Python -m build_tools.package_installer payload $AppDirectory $Payload
}

$InstallerStub = Join-Path $BuildRoot "Installer.stub.exe"
Invoke-Checked "编译安装器" {
    & $Csc `
        /nologo `
        /target:winexe `
        "/out:$InstallerStub" `
        "/resource:$(Join-Path $Root 'VERSION'),RockKingdomShinyCounter.VERSION" `
        /r:System.Windows.Forms.dll `
        /r:System.Drawing.dll `
        /r:System.Management.dll `
        /r:System.IO.Compression.dll `
        /r:System.IO.Compression.FileSystem.dll `
        /r:System.Web.Extensions.dll `
        packaging\Compatibility.cs `
        packaging\ProductVersion.cs `
        packaging\AppendedPayload.cs `
        packaging\PayloadManifest.cs `
        packaging\RuntimeProbe.cs `
        packaging\StagedInstall.cs `
        packaging\Installer.cs
}

$IsCandidate = $ReuseEnvironment -or $SkipTests -or $SkipLocalGpuProbe
$Suffix = if ($IsCandidate) { "-candidate" } else { "" }
$Setup = Join-Path $OutputRoot "RockKingdomShinyCounter-Setup-v$Version-GPU$Suffix.exe"
Invoke-Checked "封装离线安装包" {
    & $Python -m build_tools.package_installer append $InstallerStub $Payload $Setup
}

$SetupHash = (Get-FileHash -LiteralPath $Setup -Algorithm SHA256).Hash.ToLowerInvariant()
$PayloadHash = (Get-FileHash -LiteralPath $Payload -Algorithm SHA256).Hash.ToLowerInvariant()
$WheelhouseManifestHash = $null
if (Test-Path -LiteralPath $WheelhouseManifest -PathType Leaf) {
    $WheelhouseManifestHash = (
        Get-FileHash -LiteralPath $WheelhouseManifest -Algorithm SHA256
    ).Hash.ToLowerInvariant()
}
$ReleaseManifest = [ordered]@{
    version = $Version
    setup = [IO.Path]::GetFileName($Setup)
    setup_bytes = (Get-Item -LiteralPath $Setup).Length
    setup_sha256 = $SetupHash
    payload_sha256 = $PayloadHash
    wheelhouse_manifest_sha256 = $WheelhouseManifestHash
    local_gpu_probe = $ProbeStatus
    reused_environment = [bool]$ReuseEnvironment
    tests_skipped = [bool]$SkipTests
    candidate = [bool]$IsCandidate
    build_environment = (
        Get-Content -LiteralPath $BuildEnvironment -Raw | ConvertFrom-Json
    )
}
$ReleaseManifest |
    ConvertTo-Json -Depth 10 |
    Set-Content -LiteralPath (Join-Path $OutputRoot "release-manifest.json") -Encoding utf8

Write-Host ""
Write-Host "构建完成：$Setup"
Write-Host "SHA-256：$SetupHash"
if ($IsCandidate) {
    Write-Warning "这是 candidate：构建复用了环境、跳过了测试或未执行本机 GPU 探针；安装器仍会在替换旧版本前强制执行 GPU-only 探针。"
}
