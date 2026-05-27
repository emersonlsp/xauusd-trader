$Source = "F:\Codex\xauusd-bot\artifacts\trader\combined_trader_artifact.json"
$Target = "F:\Codex\xauusd-trader\artifacts\trader\combined_trader_artifact.json"

if (!(Test-Path -LiteralPath $Source)) {
  throw "Artifact source not found: $Source"
}

Copy-Item -LiteralPath $Source -Destination $Target -Force
Write-Host "Artifact synced to $Target"

