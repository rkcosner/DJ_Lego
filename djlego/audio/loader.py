"""Decode an MP4 / MP3 / WAV / etc. into a float32 stereo numpy array.

Two decode paths, chosen so the app degrades gracefully:

* **WAV** is read with the Python standard library (``wave``) -- no native
  DLLs at all -- so it works even on locked-down / managed machines where a
  security policy might block third-party binaries.
* **Everything else** (MP4, MP3, M4A, ...) uses **PyAV**, a pip-installable
  binding that bundles ffmpeg, so students need no system ffmpeg install.

Both paths return a fixed ``(n_samples, 2) float32`` array in ``[-1, 1]`` at the
requested sample rate, so the rest of the app never worries about formats.
"""

from __future__ import annotations

import os
import sys
import wave
import shutil
import tempfile
import subprocess

import numpy as np
from scipy import signal


class AudioLoadError(Exception):
    """Raised when a file cannot be decoded into usable audio."""


# --------------------------------------------------------------------------- #
# shared post-processing
# --------------------------------------------------------------------------- #


def _to_stereo(data: np.ndarray) -> np.ndarray:
    """Force an ``(n, channels)`` array to exactly two channels."""
    if data.ndim == 1:
        data = data[:, None]
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]
    return data


def _finalize(data: np.ndarray, src_sr: int, target_sr: int) -> tuple[np.ndarray, int]:
    data = _to_stereo(np.asarray(data, dtype=np.float32))
    if src_sr != target_sr:
        data = signal.resample_poly(data, target_sr, src_sr, axis=0).astype(np.float32)
    peak = float(np.max(np.abs(data))) if data.size else 0.0
    if peak > 1.0:
        data = data / peak
    return np.ascontiguousarray(data, dtype=np.float32), target_sr


# --------------------------------------------------------------------------- #
# WAV via the standard library (no native dependencies)
# --------------------------------------------------------------------------- #

_WAV_DTYPES = {1: np.uint8, 2: np.int16, 4: np.int32}


def _load_wav_stdlib(path: str, target_sr: int) -> tuple[np.ndarray, int]:
    with wave.open(path, "rb") as w:
        nch = w.getnchannels()
        sampwidth = w.getsampwidth()
        src_sr = w.getframerate()
        raw = w.readframes(w.getnframes())

    dtype = _WAV_DTYPES.get(sampwidth)
    if dtype is None:
        raise AudioLoadError(f"Unsupported WAV sample width: {sampwidth} bytes.")

    arr = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if nch > 1:
        arr = arr.reshape(-1, nch)
    # Normalise integer PCM to [-1, 1].
    if dtype == np.uint8:  # 8-bit PCM is unsigned, centred at 128
        arr = (arr - 128.0) / 128.0
    elif dtype == np.int16:
        arr = arr / 32768.0
    elif dtype == np.int32:
        arr = arr / 2147483648.0
    return _finalize(arr, src_sr, target_sr)


# --------------------------------------------------------------------------- #
# everything else via PyAV (bundled ffmpeg)
# --------------------------------------------------------------------------- #


def _as_list(frames):
    """PyAV's ``resample`` returns either a frame, a list, or None."""
    if frames is None:
        return []
    if isinstance(frames, list):
        return frames
    return [frames]


def _load_pyav(path: str, target_sr: int) -> tuple[np.ndarray, int]:
    try:
        import av
    except Exception as exc:  # noqa: BLE001
        raise AudioLoadError(_pyav_blocked_msg(exc)) from exc

    try:
        with av.open(path) as container:
            if not container.streams.audio:
                raise AudioLoadError(f"No audio stream found in {path!r}.")
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(
                format="fltp", layout="stereo", rate=target_sr
            )
            chunks: list[np.ndarray] = []
            for frame in container.decode(stream):
                for rframe in _as_list(resampler.resample(frame)):
                    chunks.append(rframe.to_ndarray())
            for rframe in _as_list(resampler.resample(None)):
                chunks.append(rframe.to_ndarray())
    except AudioLoadError:
        raise
    except ImportError as exc:  # a bundled DLL failed to load (e.g. blocked)
        raise AudioLoadError(_pyav_blocked_msg(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise AudioLoadError(f"Could not decode {os.path.basename(path)}: {exc}") from exc

    if not chunks:
        raise AudioLoadError(f"Decoded zero audio samples from {path!r}.")
    data = np.concatenate(chunks, axis=1).T  # (n, 2)
    # PyAV already resampled to target_sr and stereo.
    return _finalize(data, target_sr, target_sr)


def _pyav_blocked_msg(exc: Exception) -> str:
    return (
        "The bundled media decoder (PyAV/ffmpeg) could not be loaded on this "
        f"machine ({exc}).\n\n"
        "This usually means a managed/corporate security policy is blocking "
        "its DLLs."
    )


# --------------------------------------------------------------------------- #
# Windows Media Foundation fallback (works under enforced WDAC / Application
# Control, because it uses only Microsoft-signed OS codecs — no third-party
# DLLs).  We shell out to PowerShell + the WinRT MediaTranscoder to turn the
# song into a temporary WAV, then read that WAV with the stdlib path.
# --------------------------------------------------------------------------- #

_MF_SCRIPT = r"""
param([Parameter(Mandatory=$true)][string]$InPath,
      [Parameter(Mandatory=$true)][string]$OutPath)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null
$asTaskOp = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and
  $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function AwaitOp($op, $T) {
  $task = $asTaskOp.MakeGenericMethod($T).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
$asTaskActProg = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and
  $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncActionWithProgress`1' })[0]
function AwaitActProg($act, $TP) {
  $task = $asTaskActProg.MakeGenericMethod($TP).Invoke($null, @($act)); $task.Wait(-1) | Out-Null }
[void][Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
[void][Windows.Storage.StorageFolder,Windows.Storage,ContentType=WindowsRuntime]
[void][Windows.Media.Transcoding.MediaTranscoder,Windows.Media,ContentType=WindowsRuntime]
[void][Windows.Media.MediaProperties.MediaEncodingProfile,Windows.Media,ContentType=WindowsRuntime]
$InPath = (Resolve-Path $InPath).Path
$outDir = Split-Path -Parent $OutPath
$outName = Split-Path -Leaf $OutPath
$inFile  = AwaitOp ([Windows.Storage.StorageFile]::GetFileFromPathAsync($InPath)) ([Windows.Storage.StorageFile])
$folder  = AwaitOp ([Windows.Storage.StorageFolder]::GetFolderFromPathAsync($outDir)) ([Windows.Storage.StorageFolder])
$outFile = AwaitOp ($folder.CreateFileAsync($outName, [Windows.Storage.CreationCollisionOption]::ReplaceExisting)) ([Windows.Storage.StorageFile])
$profile = [Windows.Media.MediaProperties.MediaEncodingProfile]::CreateWav([Windows.Media.MediaProperties.AudioEncodingQuality]::High)
$transcoder = New-Object Windows.Media.Transcoding.MediaTranscoder
$prep = AwaitOp ($transcoder.PrepareFileTranscodeAsync($inFile, $outFile, $profile)) ([Windows.Media.Transcoding.PrepareTranscodeResult])
if (-not $prep.CanTranscode) { Write-Error ("Cannot transcode: " + $prep.FailureReason); exit 2 }
AwaitActProg ($prep.TranscodeAsync()) ([double])
"""


def _load_via_media_foundation(path: str, target_sr: int) -> tuple[np.ndarray, int]:
    if sys.platform != "win32":
        raise AudioLoadError("Media Foundation fallback is only available on Windows.")

    tmpdir = tempfile.mkdtemp(prefix="djlego_mf_")
    script_path = os.path.join(tmpdir, "mf_transcode.ps1")
    out_wav = os.path.join(tmpdir, "out.wav")
    try:
        with open(script_path, "w", encoding="utf-8") as fh:
            fh.write(_MF_SCRIPT)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", script_path,
                "-InPath", os.path.abspath(path), "-OutPath", out_wav,
            ],
            capture_output=True, text=True, timeout=300, creationflags=creationflags,
        )
        if proc.returncode != 0 or not os.path.exists(out_wav):
            detail = (proc.stderr or proc.stdout or "").strip()
            raise AudioLoadError(
                "Windows Media Foundation could not decode this file "
                f"({os.path.basename(path)}). {detail}"
            )
        return _load_wav_stdlib(out_wav, target_sr)
    except subprocess.TimeoutExpired as exc:
        raise AudioLoadError("Media Foundation transcode timed out.") from exc
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# --------------------------------------------------------------------------- #
# public entry point
# --------------------------------------------------------------------------- #


def load_audio(path: str, target_sr: int = 44100) -> tuple[np.ndarray, int]:
    """Return ``(samples, sample_rate)`` where ``samples`` is ``(n, 2)`` float32.

    WAV is decoded with the standard library; every other container goes
    through PyAV.  Raises :class:`AudioLoadError` with a helpful message on
    failure.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in (".wav", ".wave"):
        try:
            return _load_wav_stdlib(path, target_sr)
        except AudioLoadError:
            raise
        except Exception:  # noqa: BLE001 - malformed WAV: let PyAV try
            pass

    # Primary: PyAV (cross-platform, bundled ffmpeg).  If it's blocked -- e.g.
    # an enforced WDAC / Application Control policy won't load its DLLs -- fall
    # back on Windows to Media Foundation, which uses signed OS codecs.
    try:
        return _load_pyav(path, target_sr)
    except AudioLoadError as pyav_err:
        if sys.platform == "win32":
            try:
                return _load_via_media_foundation(path, target_sr)
            except AudioLoadError as mf_err:
                raise AudioLoadError(
                    f"{pyav_err}\n\nThe Windows Media Foundation fallback also "
                    f"failed: {mf_err}\n\nWAV files always work; try converting "
                    "the song to WAV."
                ) from mf_err
        raise
