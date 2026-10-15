# QMP screendump helper for vm-boot-proof.ps1
function Invoke-QmpScreendump {
  param(
    [int]$Port = 4445,
    [string]$PngPath,
    [string]$PpmPath = ""
  )
  $result = @{ Ok = $false; Detail = "unknown"; Path = $null }
  if (-not $PpmPath) { $PpmPath = [IO.Path]::ChangeExtension($PngPath, ".ppm") }
  try {
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect("127.0.0.1", $Port)
    $stream = $client.GetStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true
    $null = $reader.ReadLine() # greeting
    $writer.WriteLine('{"execute":"qmp_capabilities"}')
    for ($i = 0; $i -lt 8; $i++) {
      $line = $reader.ReadLine()
      if ($line -match '"return"\s*:\s*\{\s*\}') { break }
    }
    $ppmQ = ($PpmPath -replace '\\', '/')
    $cmd = @{ execute = "screendump"; arguments = @{ filename = $ppmQ } } | ConvertTo-Json -Compress
    $writer.WriteLine($cmd)
    for ($i = 0; $i -lt 12; $i++) {
      $line = $reader.ReadLine()
      if ($line -match '"return"\s*:\s*\{\s*\}') { break }
      if ($line -match '"error"') { throw "QMP error: $line" }
    }
    $client.Close()
    # Wait for QEMU to finish writing PPM (TCG can be slow).
    $ppmReady = $false
    for ($w = 0; $w -lt 25; $w++) {
      Start-Sleep -Milliseconds 200
      if ((Test-Path $PpmPath) -and ((Get-Item $PpmPath).Length -gt 1000)) { $ppmReady = $true; break }
    }
    if (-not $ppmReady) {
      $result.Detail = "ppm_missing"
      return $result
    }
    # QEMU writes PPM; convert with magick/ffmpeg if present, else keep PPM path.
    $outPath = $PngPath
    $magick = Get-Command magick -ErrorAction SilentlyContinue
    if ($magick) {
      & magick convert $PpmPath $PngPath 2>$null
      if (Test-Path $PngPath) { Remove-Item $PpmPath -Force -ErrorAction SilentlyContinue }
    } else {
      $ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
      if ($ffmpeg) {
        & ffmpeg -y -loglevel error -i $PpmPath $PngPath 2>$null | Out-Null
        if (Test-Path $PngPath) { Remove-Item $PpmPath -Force -ErrorAction SilentlyContinue }
      } else {
        $outPath = $PpmPath
        Copy-Item $PpmPath $PngPath -Force -ErrorAction SilentlyContinue
      }
    }
    if ((Test-Path $outPath) -and ((Get-Item $outPath).Length -gt 800)) {
      $result.Ok = $true
      $result.Path = $outPath
      $result.Detail = "ok $outPath"
    } else {
      $result.Detail = "image_too_small_or_missing"
    }
  } catch {
    $result.Detail = $_.Exception.Message
  }
  return $result
}
