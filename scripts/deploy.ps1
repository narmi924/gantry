# Deploy Gantry to Azure Container Apps: infrastructure, image, app.
#   ./scripts/deploy.ps1 -ResourceGroup rg-gantry -Foundry gantry-foundry-di23
param(
  [Parameter(Mandatory)] [string] $ResourceGroup,
  [Parameter(Mandatory)] [string] $Foundry,
  [string] $Project = "gantry",
  [string] $Tag = (Get-Date -Format "yyyyMMddHHmm")
)
$ErrorActionPreference = "Stop"

# 1. the environment, registry, monitoring and the app (with a placeholder image the first time)
$out = az deployment group create -g $ResourceGroup -f infra/main.bicep -p foundryName=$Foundry projectName=$Project `
  --query properties.outputs -o json | ConvertFrom-Json
$registry = $out.registry.value

# 2. the produced broadcast goes inside the image: from this machine, or else from the repository's release
$production = "backend/data/productions/demo-analyst_en+audio_en+casual_en+home_en/rundown.json"
if (-not (Test-Path $production)) {
  Write-Host "No produced broadcast here; fetching it from the release"
  gh release download --repo narmi924/gantry --pattern "gantry-demo-production.zip" --dir $env:TEMP --clobber
  Expand-Archive -Force (Join-Path $env:TEMP "gantry-demo-production.zip") "backend/data/productions"
}
if (-not (Test-Path $production)) {
  throw "The default broadcast hasn't been produced. Run: cd backend; uv run python -m gantry.crew.produce --id demo"
}

# 3. build the image in the registry, with the produced broadcast inside it
az acr build -r $registry.Split(".")[0] -t "gantry:$Tag" .

# 4. point the app at it
az deployment group create -g $ResourceGroup -f infra/main.bicep -p foundryName=$Foundry projectName=$Project `
  image="$registry/gantry:$Tag" | Out-Null
Write-Host "Gantry is live at $($out.url.value)"
