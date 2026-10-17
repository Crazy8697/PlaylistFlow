# Build Playlist Flow (PyInstaller onedir: dist\PlaylistFlow\PlaylistFlow.exe) and its Windows installer.
#   .\build.ps1                  build only (dist\ and build\ are gitignored)
#   .\build.ps1 -Setup           build, then package dist\PlaylistFlow as PlaylistFlow-Setup-<version>.exe (+ .sha256)
#                                with Inno Setup 6 (ISCC; a build tool only) into -SetupDir, plus the same installer
#                                as PlaylistFlow-Setup.exe (+ .sha256), the constant name the updater and download
#                                links use; then copy the versioned pair to -DownloadsDir (unless -NoDownloads)
#   .\build.ps1 -Setup -NoBuild  package the existing dist\PlaylistFlow without rebuilding
#   .\build.ps1 -PrivacyCheck    run tools\privacy_check.py on the tree (and on dist\PlaylistFlow if built), nothing else
#   .\build.ps1 -Release -Version x.y.z [-FreshPublicHistory]
#                                publish, the Lazarus PDF way. Refuses unless this tree is clean in git, x.y.z is
#                                playlistflow.__version__, release-notes\vx.y.z.md exists, the release isn't on
#                                GitHub yet, the tag isn't in the private repo yet, and tools\privacy_check.py finds
#                                nothing in the tree; then builds the Setup and runs the privacy check again on the
#                                frozen build, refusing on any finding. Then:
#                                  1. the public source: a clone of Crazy8697/PlaylistFlow in -PublicDir gets exactly
#                                     this tree's committed files (git archive of HEAD, so none of the private
#                                     history), checked once more by privacy_check as it stands, and ONE commit
#                                     "Playlist Flow x.y.z" authored by the GitHub noreply identity, never this
#                                     machine's. -FreshPublicHistory (the very first release only) starts the public
#                                     history over from that single commit and force-pushes it;
#                                  2. release vx.y.z on Crazy8697/PlaylistFlow on that commit: created as a draft,
#                                     the assets uploaded (PlaylistFlow-Setup-x.y.z.exe, its .sha256,
#                                     PlaylistFlow-Setup.exe, its .sha256), then published as the latest release;
#                                  3. tag vx.y.z on the private commit, pushed to Forgejo only.
# The private working copy (Forgejo) never reaches GitHub: its github-public remote has pushes disabled, and the public
# clone in -PublicDir is a separate folder that only this script commits to.
# Needs a Python 3.11 venv with requirements.txt installed (PLAYLISTFLOW_PY = its python.exe if it isn't .venv here),
# the GitHub CLI (gh) signed in, and Inno Setup 6.
param(
    [switch]$Setup,
    [switch]$NoBuild,
    [switch]$PrivacyCheck,
    [switch]$Release,
    [string]$Version = "",
    [switch]$FreshPublicHistory,    # -Release only, once, deliberately: the public repo restarts from this release's
                                    # single commit (force-pushed), dropping whatever history it had
    [string]$SetupDir = (Join-Path $PSScriptRoot "dist\installer"),
    [string]$DownloadsDir = (Join-Path $env:USERPROFILE "Downloads"),
    [switch]$NoDownloads,
    [string]$PublicDir = (Join-Path $env:LOCALAPPDATA "PlaylistFlow-public\PlaylistFlow")
)
$ErrorActionPreference = "Stop"
$PublicRepo = "Crazy8697/PlaylistFlow"
$PublicUrl = "git@github.com:$PublicRepo.git"
$PublicName = "Crazy8697"
$PublicEmail = "261646346+Crazy8697@users.noreply.github.com"
# Python: $env:PLAYLISTFLOW_PY, else .venv next to this script, else python on PATH
$py = if ($env:PLAYLISTFLOW_PY) { $env:PLAYLISTFLOW_PY }
      elseif (Test-Path (Join-Path $PSScriptRoot ".venv\Scripts\python.exe")) { Join-Path $PSScriptRoot ".venv\Scripts\python.exe" }
      else { "python" }

# ---- the public source sync: exactly the committed tree, one commit on the public history ----
function Sync-Public([string]$ver, [switch]$Fresh) {
    if (-not (Test-Path (Join-Path $PublicDir ".git"))) {
        New-Item -ItemType Directory -Force (Split-Path $PublicDir) | Out-Null
        # (through cmd: PowerShell 5.1 turns a redirected native stderr into an error under "Stop")
        cmd /c "git clone -q $PublicUrl `"$PublicDir`" 2>&1"
        if ($LASTEXITCODE -ne 0) { throw "Couldn't clone $PublicRepo" }
    } elseif (-not $Fresh) {
        git -C $PublicDir pull -q --ff-only
        if ($LASTEXITCODE -ne 0) { throw "Couldn't update the public clone" }
    }
    if ($Fresh) {
        git -C $PublicDir checkout -q --orphan playlistflow-fresh
        if ($LASTEXITCODE -ne 0) { throw "Couldn't start a fresh history" }
    }
    $tar = Join-Path $env:TEMP "playlistflow-public-$ver.tar"
    git -C $PSScriptRoot archive --format=tar -o $tar HEAD
    if ($LASTEXITCODE -ne 0) { throw "git archive failed" }
    # -f: on a fresh (orphan) branch every file is still staged
    git -C $PublicDir rm -r -q -f --ignore-unmatch -- . | Out-Null
    Get-ChildItem $PublicDir -Force | Where-Object { $_.Name -ne ".git" } | Remove-Item -Recurse -Force
    # Windows' own tar: a GNU tar earlier on PATH (Git's) reads "C:" as a remote host
    & (Join-Path $env:SystemRoot "System32\tar.exe") -xf $tar -C $PublicDir
    if ($LASTEXITCODE -ne 0) { throw "Couldn't unpack the source into the public clone" }
    Remove-Item $tar
    $nfiles = (Get-ChildItem $PublicDir -Recurse -File -Force | Where-Object { $_.FullName -notlike "*\.git\*" }).Count
    if ($nfiles -lt 20) { throw "Only $nfiles files in the public clone: refusing to publish" }
    # the tree that is about to go public, checked once more exactly as it stands
    & $py (Join-Path $PSScriptRoot "tools\privacy_check.py") --root $PublicDir
    if ($LASTEXITCODE -ne 0) { throw "The privacy check found something in the public clone; nothing was published." }
    git -C $PublicDir add -A
    git -C $PublicDir -c "user.name=$PublicName" -c "user.email=$PublicEmail" commit -q -m "Playlist Flow $ver"
    if ($LASTEXITCODE -ne 0) { throw "Nothing to commit in the public clone?" }
    if ($Fresh) {
        cmd /c "git -C `"$PublicDir`" branch -D main >nul 2>&1"
        git -C $PublicDir branch -m main
        # -u: the branch rename drops upstream tracking; this restores it (the Lazarus PDF fix)
        git -C $PublicDir push -q --force -u origin main
    } else {
        git -C $PublicDir push -q -u origin main
    }
    if ($LASTEXITCODE -ne 0) { throw "Couldn't push the public source" }
    $script:PublicCommit = (git -C $PublicDir rev-parse HEAD).Trim()
    Write-Host "Public source pushed: $PublicRepo main = $script:PublicCommit"
}

Push-Location $PSScriptRoot
try {
    $ver = (Select-String -Path (Join-Path $PSScriptRoot "playlistflow\__init__.py") -Pattern '^__version__ = "([^"]+)"').Matches[0].Groups[1].Value
    if (-not $ver) { throw "__version__ not found in playlistflow\__init__.py" }

    $privacy = Join-Path $PSScriptRoot "tools\privacy_check.py"
    if ($PrivacyCheck) {
        $pargs = @($privacy)
        if (Test-Path (Join-Path $PSScriptRoot "dist\PlaylistFlow\PlaylistFlow.exe")) { $pargs += "--dist" }
        & $py @pargs
        if ($LASTEXITCODE -ne 0) { throw "The privacy check found something." }
        return
    }
    if ($FreshPublicHistory -and -not $Release) { throw "-FreshPublicHistory goes with -Release." }
    if ($Release) {
        if ($Version -ne $ver) { throw "-Version '$Version' doesn't match playlistflow.__version__ ($ver)." }
        $dirty = git -C $PSScriptRoot status --porcelain
        if ($LASTEXITCODE -ne 0) { throw "git status failed" }
        if ($dirty) { throw "The Playlist Flow tree isn't clean in git; commit (to Forgejo) first." }
        # The privacy gate: nothing past this line runs if the tree carries anything private.
        & $py $privacy
        if ($LASTEXITCODE -ne 0) { throw "The privacy check found something in the tree; nothing was built or published." }
        if ($NoBuild) { throw "-Release always builds fresh." }
        $notes = Join-Path $PSScriptRoot "release-notes\v$ver.md"
        if (-not (Test-Path $notes)) { throw "No release notes: $notes" }
        cmd /c "gh repo view $PublicRepo >nul 2>&1"
        if ($LASTEXITCODE -ne 0) { throw "$PublicRepo doesn't exist (or gh can't see it); create it first." }
        cmd /c "gh release view v$ver --repo $PublicRepo >nul 2>&1"
        if ($LASTEXITCODE -eq 0) { throw "Release v$ver already exists on $PublicRepo." }
        if (git -C $PSScriptRoot tag --list "v$ver") { throw "Tag v$ver already exists in the private repo." }
        $Setup = $true
    }

    $dist = Join-Path $PSScriptRoot "dist\PlaylistFlow"
    if (-not $NoBuild) {
        & $py -m PyInstaller --noconfirm --clean PlaylistFlow.spec
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)" }
    }
    if (-not (Test-Path (Join-Path $dist "PlaylistFlow.exe"))) { throw "No build in $dist" }
    # Nothing personal ships: no keys, no logs in the build.
    $leaks = Get-ChildItem $dist -Recurse -File -Force | Where-Object { $_.Name -like ".env*" -or $_.Extension -eq ".log" }
    if ($leaks) { throw "Refusing: found in the build: $($leaks.FullName -join ', ')" }
    # Only the icon font THIRD-PARTY-NOTICES.md covers may ship (Material Design Icons 6).
    $fonts = Get-ChildItem (Join-Path $dist "_internal\qtawesome\fonts") -File -ErrorAction SilentlyContinue |
             Where-Object { $_.Name -notlike "materialdesignicons6-webfont*" }
    if ($fonts) { throw "Refusing: icon fonts the notices don't cover are in the build: $($fonts.Name -join ', ')" }
    $mb = [math]::Round((Get-ChildItem $dist -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
    Write-Host "Built: $dist\PlaylistFlow.exe  ($mb MB, version $ver)"

    if ($Setup) {
        # Inno Setup's compiler: $env:PLAYLISTFLOW_ISCC, else where its installer registered it
        $iscc = $env:PLAYLISTFLOW_ISCC
        if (-not $iscc) {
            foreach ($k in "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
                           "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
                           "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1") {
                $loc = (Get-ItemProperty $k -ErrorAction SilentlyContinue).InstallLocation
                if ($loc -and (Test-Path (Join-Path $loc "ISCC.exe"))) { $iscc = Join-Path $loc "ISCC.exe"; break }
            }
        }
        if (-not $iscc -or -not (Test-Path $iscc)) { throw "Inno Setup 6 (ISCC.exe) not found; set PLAYLISTFLOW_ISCC" }
        New-Item -ItemType Directory -Force $SetupDir | Out-Null
        Get-ChildItem $SetupDir -Filter "PlaylistFlow-Setup*" -ErrorAction SilentlyContinue | Remove-Item -Force
        & $iscc /Q "/DAppVersion=$ver" "/DDistDir=$dist" "/O$SetupDir" (Join-Path $PSScriptRoot "_installer.iss")
        if ($LASTEXITCODE -ne 0) { throw "ISCC failed ($LASTEXITCODE)" }
        $base = "PlaylistFlow-Setup-$ver.exe"
        $out = Join-Path $SetupDir $base
        $hash = (Get-FileHash $out -Algorithm SHA256).Hash.ToLower()
        Set-Content -Path "$out.sha256" -Value "$hash *$base" -Encoding ascii -NoNewline
        # the constant-named copy: what the in-program updater looks for on a release
        # (PlaylistFlow-Setup.exe + PlaylistFlow-Setup.exe.sha256), and the stable download link
        $plain = Join-Path $SetupDir "PlaylistFlow-Setup.exe"
        Copy-Item $out $plain -Force
        Set-Content -Path "$plain.sha256" -Value "$hash *PlaylistFlow-Setup.exe" -Encoding ascii -NoNewline
        $smb = [math]::Round((Get-Item $out).Length / 1MB, 1)
        Write-Host "Setup: $out  ($smb MB, version $ver)"
        Write-Host "SHA-256: $hash"
    }

    if ($Release) {
        & $py $privacy --dist
        if ($LASTEXITCODE -ne 0) { throw "The privacy check found something in the build; nothing was published." }
        Write-Host "Release gate passed for $ver."

        # 1. the public source
        $script:PublicCommit = $null
        Sync-Public $ver -Fresh:$FreshPublicHistory
        if (-not $script:PublicCommit) { throw "The public sync didn't report its commit; nothing was released." }

        # 2. the release, on that commit: a draft first, so nobody ever sees a release without its
        #    checksums, then published as the latest release in one step
        $assets = @($out, "$out.sha256", $plain, "$plain.sha256")
        gh release create "v$ver" $assets[0] --repo $PublicRepo --target $script:PublicCommit `
            --title "Playlist Flow $ver" --notes-file $notes --draft
        if ($LASTEXITCODE -ne 0) { throw "gh release create failed ($LASTEXITCODE)" }
        foreach ($a in $assets[1..3]) {
            gh release upload "v$ver" $a --repo $PublicRepo
            if ($LASTEXITCODE -ne 0) { throw "Uploading $a failed; the release is still a draft on $PublicRepo." }
        }
        $names = ((gh release view "v$ver" --repo $PublicRepo --json assets --jq ".assets[].name") | Sort-Object) -join ","
        $want = (($assets | ForEach-Object { Split-Path $_ -Leaf }) | Sort-Object) -join ","
        if ($names -ne $want) { throw "Assets are '$names', not '$want'; the release is still a draft." }
        gh release edit "v$ver" --repo $PublicRepo --draft=false --latest
        if ($LASTEXITCODE -ne 0) { throw "Publishing the draft failed; it is still a draft on $PublicRepo." }
        Write-Host "Released v$ver on $PublicRepo (public commit $script:PublicCommit), assets: $names"

        # 3. the same tag on the private commit, to Forgejo only
        git -C $PSScriptRoot tag "v$ver"
        git -C $PSScriptRoot push -q origin "refs/tags/v$ver"
        if ($LASTEXITCODE -ne 0) { throw "Pushing tag v$ver to Forgejo failed (the GitHub release is out)." }
        Write-Host "Tagged v$ver on the private commit and pushed the tag to Forgejo."
    }

    if ($Setup -and -not $NoDownloads -and $DownloadsDir) {
        Copy-Item $out, "$out.sha256" $DownloadsDir -Force
        Write-Host "Copied $base and $base.sha256 to $DownloadsDir"
    }
} finally { Pop-Location }
