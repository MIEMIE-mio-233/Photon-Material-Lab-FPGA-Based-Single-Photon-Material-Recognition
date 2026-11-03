<#
.SYNOPSIS
在独立英文目录中构建 Vivado/Vitis 2025.2 Overlay。
.EXAMPLE
powershell -ExecutionPolicy Bypass -File build/scripts/build_2025_2.ps1 -WorkDirectory D:\fpga_build\photon_2025_2
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$WorkDirectory,
    [string]$VivadoCommand='vivado',
    [string]$HlsCommand='vitis-run',
    [switch]$PrepareOnly,
    [switch]$RunCosim
)
$ErrorActionPreference='Stop'
$repoRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$workRoot=[IO.Path]::GetFullPath($WorkDirectory)
if ($workRoot -match '[^\x20-\x7E]') {throw 'WorkDirectory must contain ASCII characters only.'}
$sep=[IO.Path]::DirectorySeparatorChar
if ($workRoot.TrimEnd($sep) -eq [IO.Path]::GetPathRoot($workRoot).TrimEnd($sep)) {throw 'Choose a dedicated subdirectory, not a drive root.'}
if ($workRoot.StartsWith($repoRoot.TrimEnd($sep)+$sep,[StringComparison]::OrdinalIgnoreCase) -or $workRoot -eq $repoRoot) {throw 'Choose a workspace outside the source repository.'}
if (Test-Path -LiteralPath $workRoot) {
    if (Get-ChildItem -LiteralPath $workRoot -Force | Select-Object -First 1) {throw 'WorkDirectory must be empty. Use a new directory for each clean build.'}
}
$required=@('src\hls\tdc_accelerator.cpp','src\hls\build_hls_2025_2.tcl','src\bd\design_1.bd','src\netlist\time_merge_eval.dcp','src\rtl\pynq_top.v','sim\hls\histogram.bin','sim\hls\model.bin','sim\hls\expected.bin','sim\hls\dimensions.bin','sim\hls\baseline.bin','sim\hls\check_rtl.cpp')
foreach($relative in $required) {if(-not(Test-Path -LiteralPath (Join-Path $repoRoot $relative))) {throw "Missing source: $relative"}}
if(-not $PrepareOnly) {
    $vivado=(Get-Command $VivadoCommand -ErrorAction Stop).Source
    $hls=(Get-Command $HlsCommand -ErrorAction Stop).Source
    $versionText=(& $vivado -version 2>&1 | Out-String)
    # 2025.2的loader.bat对-version纯查询固定返回1,以版本文本为准；真实构建阶段仍检查退出码。
    if($versionText -notmatch 'Vivado\s+v?2025\.2(?:\D|$)') {
        if($LASTEXITCODE -ne 0) {throw "Cannot query Vivado version (exit $LASTEXITCODE). Load the 2025.2 tool environment. Output: $versionText"}
        throw "Vivado 2025.2 required. Detected: $versionText"
    }
    $hlsVersionText=(& $hls --version 2>&1 | Out-String)
    if($LASTEXITCODE -ne 0) {throw "Cannot query Vitis version (exit $LASTEXITCODE): $hlsVersionText"}
    if($hlsVersionText -notmatch '(?<![0-9])2025\.2(?:\D|$)') {throw "Vitis 2025.2 required. Detected: $hlsVersionText"}

}
$project=Join-Path $workRoot 'project'
$logs=Join-Path $workRoot 'logs'
New-Item -ItemType Directory -Force -Path $project,$logs,(Join-Path $project 'build\scripts'),(Join-Path $project 'sim'),(Join-Path $project 'board\overlays') | Out-Null
Copy-Item -LiteralPath (Join-Path $repoRoot 'src') -Destination $project -Recurse
Copy-Item -LiteralPath (Join-Path $repoRoot 'sim\hls') -Destination (Join-Path $project 'sim') -Recurse
Get-ChildItem -LiteralPath $PSScriptRoot -File | Copy-Item -Destination (Join-Path $project 'build\scripts')
# 保存本次硬件输入哈希，便于定位工具升级前后的变化。
$inputs=Get-ChildItem -LiteralPath (Join-Path $project 'src'),(Join-Path $project 'sim\hls'),(Join-Path $project 'build\scripts') -Recurse -File | ForEach-Object {
    [ordered]@{path=$_.FullName.Substring($project.Length+1).Replace('\','/');sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
}
[ordered]@{target_version='2025.2';prepared_at=(Get-Date).ToString('o');run_cosim=[bool]$RunCosim;inputs=@($inputs)} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $workRoot 'build_inputs.json') -Encoding UTF8
if($PrepareOnly) {Write-Output "PREPARED: $project"; return}
$versionText | Set-Content -LiteralPath (Join-Path $logs 'vivado_version.txt') -Encoding UTF8
$hlsVersionText | Set-Content -LiteralPath (Join-Path $logs 'vitis_version.txt') -Encoding UTF8
$hadCosim=Test-Path Env:TDC_HLS_COSIM
$oldCosim=$env:TDC_HLS_COSIM
function Invoke-BuildStage([string]$Name,[string]$Program,[string[]]$Arguments) {
    Write-Output "STAGE: $Name"
    & $Program @Arguments 2>&1 | Tee-Object -FilePath (Join-Path $logs ($Name+'.log'))
    if($LASTEXITCODE -ne 0) {throw "$Name failed with exit code $LASTEXITCODE. See $logs"}
}
Push-Location $project
try {
    $env:TDC_HLS_COSIM=if($RunCosim){'1'}else{'0'}
    Invoke-BuildStage '01_hls' $hls @('--mode','hls','--tcl','src/hls/build_hls_2025_2.tcl')
    $ipXml=Join-Path $project 'build\output\hls\solution1\impl\ip\component.xml'
    if(-not(Test-Path -LiteralPath $ipXml)) {throw "HLS IP export missing: $ipXml"}
    Invoke-BuildStage '02_project' $vivado @('-mode','batch','-source','build/scripts/create_pynq_project_2025_2.tcl')
    Invoke-BuildStage '03_bitstream' $vivado @('-mode','batch','-source','build/scripts/build_pynq_bit_2025_2.tcl')
    foreach($name in @('tdc_pynq.bit','tdc_pynq.hwh')) {
        $artifact=Join-Path $project ('board\overlays\'+$name)
        if(-not(Test-Path -LiteralPath $artifact)) {throw "Build output missing: $artifact"}
    }
    Write-Output "BUILD_COMPLETE: $(Join-Path $project 'board\overlays')"
} finally {
    Pop-Location
    if($hadCosim){$env:TDC_HLS_COSIM=$oldCosim}else{Remove-Item Env:TDC_HLS_COSIM -ErrorAction SilentlyContinue}
}
