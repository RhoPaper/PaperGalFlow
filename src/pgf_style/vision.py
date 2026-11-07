"""Optional screenshot analysis through an external vision model.

The tool does not ship a model and never requires one.  When screenshots and
an OpenAI-compatible endpoint are configured, the vision result is blended
with the evidence extracted from the game's own GUI files and assets.  The
blend weight depends on both confidences: vision is trusted more when the
local evidence is weak, and not at all when the model reports low confidence.

Configuration is intentionally environment based so an API key never appears
in shell history, generated files or diagnostic output::

    export PGF_VISION_ENDPOINT=https://api.example.com/v1/chat/completions
    export PGF_VISION_MODEL=vision-model
    export PGF_VISION_API_KEY=...
    pgf install <game> --screenshots shot1.png --screenshots shot2.png
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .colors import (
    contrast_ratio,
    darken,
    lighten,
    luminance,
    mix,
    normalize_color,
)
from .presets import preset_tokens
from .tokens import StyleTokens, default_palettes

__all__ = [
    "VisionError",
    "VisionConfig",
    "VisionStyle",
    "OpenAICompatibleVision",
    "vision_backend",
    "fuse_vision",
    "vision_tokens",
]

_IMAGE_SUFFIXES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
_COLOR_KEYS = ("accent", "panel", "background", "border", "text")
_MAX_IMAGES = 4
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_DEFAULT_TIMEOUT = 60.0

Transport = Callable[[str, dict[str, str], bytes, float], bytes]


class VisionError(ValueError):
    """The screenshot backend is not configured or returned unusable data."""


@dataclass(frozen=True)
class VisionConfig:
    endpoint: str = ""
    model: str = ""
    api_key: str = ""
    timeout: float = _DEFAULT_TIMEOUT
    max_images: int = _MAX_IMAGES
    max_image_bytes: int = _MAX_IMAGE_BYTES

    @classmethod
    def from_env(
        cls,
        *,
        endpoint: str = "",
        model: str = "",
        api_key: str = "",
        timeout: float | None = None,
    ) -> "VisionConfig":
        raw_timeout = timeout if timeout is not None else os.environ.get("PGF_VISION_TIMEOUT")
        try:
            resolved_timeout = float(raw_timeout) if raw_timeout else _DEFAULT_TIMEOUT
        except (TypeError, ValueError):
            resolved_timeout = _DEFAULT_TIMEOUT
        return cls(
            endpoint=(endpoint or os.environ.get("PGF_VISION_ENDPOINT", "")).strip(),
            model=(model or os.environ.get("PGF_VISION_MODEL", "")).strip(),
            api_key=(api_key or os.environ.get("PGF_VISION_API_KEY", "")).strip(),
            timeout=max(5.0, min(300.0, resolved_timeout)),
        )

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self.model)

    def chat_url(self) -> str:
        endpoint = self.endpoint.rstrip("/")
        if endpoint.endswith("/chat/completions"):
            return endpoint
        if endpoint.endswith("/v1"):
            return endpoint + "/chat/completions"
        return endpoint

    def describe(self) -> str:
        if not self.configured:
            return "not configured"
        return f"{self.model} @ {self.chat_url()}"


@dataclass
class VisionStyle:
    """The subset of style information a vision model can provide."""

    colors: dict[str, str] = field(default_factory=dict)
    geometry: dict[str, int] = field(default_factory=dict)
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)
    model: str = ""
    raw: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "colors": dict(self.colors),
            "geometry": dict(self.geometry),
            "confidence": round(self.confidence, 3),
            "notes": list(self.notes),
        }

    @property
    def has_style(self) -> bool:
        return bool(self.colors or self.geometry)


def _clamp_confidence(value: object, default: float = 0.5) -> float:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def _parse_geometry(value: object) -> dict[str, int]:
    geometry: dict[str, int] = {}
    if not isinstance(value, Mapping):
        return geometry
    for key, raw in value.items():
        if key not in ("corner_radius", "border_width"):
            continue
        if isinstance(raw, bool):
            continue
        try:
            number = int(raw)
        except (TypeError, ValueError):
            continue
        geometry[key] = max(0, min(32, number))
    return geometry


def parse_vision_payload(
    payload: object,
    *,
    model: str = "",
) -> VisionStyle:
    """Validate a model's JSON answer and normalise its colours."""

    if not isinstance(payload, Mapping):
        raise VisionError("vision response is not a JSON object")
    colors: dict[str, str] = {}
    raw_colors = payload.get("colors", {})
    if isinstance(raw_colors, Mapping):
        for key, value in raw_colors.items():
            if key not in _COLOR_KEYS:
                continue
            color = normalize_color(value)
            if color:
                colors[key] = color
    geometry = _parse_geometry(payload.get("geometry", {}))
    notes_raw = payload.get("notes", [])
    notes: list[str] = []
    if isinstance(notes_raw, list):
        notes = [str(note).strip()[:300] for note in notes_raw if str(note).strip()][:8]
    elif isinstance(notes_raw, str) and notes_raw.strip():
        notes = [notes_raw.strip()[:300]]
    if not colors and not geometry:
        raise VisionError("vision response contains neither colours nor geometry")
    confidence = _clamp_confidence(payload.get("confidence", 0.5))
    return VisionStyle(
        colors=colors,
        geometry=geometry,
        confidence=confidence,
        notes=notes,
        model=model,
        raw=dict(payload),
    )


def _extract_json(text: str) -> object:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise VisionError(f"vision model did not return valid JSON: {exc}") from exc
    raise VisionError("vision model did not return a JSON object")


def _urllib_transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:400]
        except Exception:  # pragma: no cover - best effort
            pass
        raise VisionError(f"vision endpoint returned HTTP {exc.code}: {detail}".strip()) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VisionError(f"could not reach vision endpoint: {exc}") from exc


class OpenAICompatibleVision:
    """A tiny OpenAI-compatible chat-completions client for image analysis."""

    def __init__(self, config: VisionConfig, transport: Transport | None = None) -> None:
        if not config.configured:
            raise VisionError(
                "vision backend is not configured; set PGF_VISION_ENDPOINT and "
                "PGF_VISION_MODEL (and PGF_VISION_API_KEY when required)"
            )
        self.config = config
        self.transport = transport or _urllib_transport

    def analyze(self, paths: Iterable[str | Path]) -> VisionStyle:
        images = self._load_images(paths)
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "Extract the UI style of this Ren'Py visual-novel game from the "
                    "screenshots. Return JSON only, with this shape: "
                    '{"colors": {"accent": "#rrggbb", "panel": "#rrggbb", '
                    '"background": "#rrggbb", "text": "#rrggbb", "border": "#rrggbb"}, '
                    '"geometry": {"corner_radius": 16, "border_width": 2}, '
                    '"confidence": 0.0, "notes": ["short evidence"]}. '
                    "Use the dialogue box / choice buttons for panel, the most "
                    "saturated repeated UI colour for accent, the chart's overall "
                    "backdrop for background and the readable text colour for text. "
                    "Confidence must reflect how clearly the UI is visible."
                ),
            }
        ]
        for mime, encoded in images:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{encoded}"},
                }
            )
        payload = {
            "model": self.config.model,
            "temperature": 0,
            "max_tokens": 700,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a precise UI colour analyst. Answer with one JSON "
                        "object only; never use markdown fences or prose."
                    ),
                },
                {"role": "user", "content": content},
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        raw = self.transport(self.config.chat_url(), headers, body, self.config.timeout)
        try:
            response = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VisionError(f"vision endpoint returned invalid JSON: {exc}") from exc
        if isinstance(response, Mapping) and response.get("error"):
            error = response["error"]
            message = error.get("message") if isinstance(error, Mapping) else str(error)
            raise VisionError(f"vision endpoint error: {message}")
        if isinstance(response, Mapping) and ("colors" in response or "geometry" in response):
            return parse_vision_payload(response, model=self.config.model)
        text = self._response_text(response)
        return parse_vision_payload(_extract_json(text), model=self.config.model)

    def _load_images(self, paths: Iterable[str | Path]) -> list[tuple[str, str]]:
        resolved: list[Path] = []
        seen: set[Path] = set()
        for raw in paths:
            path = Path(raw).expanduser()
            if not path.is_file():
                raise VisionError(f"screenshot does not exist: {path}")
            path = path.resolve()
            if path in seen:
                continue
            suffix = path.suffix.lower()
            if suffix not in _IMAGE_SUFFIXES:
                raise VisionError(f"unsupported screenshot format: {path.name}")
            if path.stat().st_size > self.config.max_image_bytes:
                raise VisionError(f"screenshot is too large: {path.name}")
            seen.add(path)
            resolved.append(path)
        if not resolved:
            raise VisionError("no screenshots were provided for vision analysis")
        if len(resolved) > self.config.max_images:
            raise VisionError(f"at most {self.config.max_images} screenshots are supported")
        images: list[tuple[str, str]] = []
        for path in resolved:
            mime = mimetypes.guess_type(path.name)[0] or _IMAGE_SUFFIXES[path.suffix.lower()]
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            images.append((mime, encoded))
        return images

    @staticmethod
    def _response_text(response: object) -> str:
        if not isinstance(response, Mapping):
            raise VisionError("vision endpoint returned an unexpected response")
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise VisionError("vision endpoint response has no choices")
        message = choices[0].get("message") if isinstance(choices[0], Mapping) else None
        content = message.get("content") if isinstance(message, Mapping) else None
        if isinstance(content, str):
            return content
        if isinstance(content, Mapping):
            return json.dumps(content, ensure_ascii=False)
        if isinstance(content, list):
            parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, Mapping) and item.get("type") in ("text", "output_text")
            ]
            return "".join(str(part) for part in parts)
        raise VisionError("vision endpoint response has no text content")


def vision_backend(
    *,
    endpoint: str = "",
    model: str = "",
    transport: Transport | None = None,
) -> OpenAICompatibleVision | None:
    """Build a backend from environment/CLI overrides, or return ``None``."""

    config = VisionConfig.from_env(endpoint=endpoint, model=model)
    if not config.configured:
        return None
    return OpenAICompatibleVision(config, transport=transport)


_COLOR_FIELDS = ("panel", "background", "accent", "border", "text")


def fuse_vision(
    tokens: StyleTokens,
    vision: VisionStyle,
    *,
    weight: float | None = None,
) -> StyleTokens:
    """Blend a vision result over existing tokens by confidence.

    The default weight is 0.2..0.5: it grows when the local evidence confidence
    is low and is scaled by the model's own confidence.
    """

    if not vision.has_style:
        return tokens
    if weight is None:
        local = max(0.0, min(1.0, float(tokens.confidence)))
        weight = (0.2 + 0.3 * (1.0 - local)) * vision.confidence
        weight = min(0.5, weight)
    weight = max(0.0, min(0.8, float(weight)))
    if weight <= 0:
        return tokens

    result = StyleTokens.from_dict(tokens.to_dict())
    changed = False
    for key in _COLOR_FIELDS:
        color = normalize_color(vision.colors.get(key, ""))
        if not color:
            continue
        if key == "text":
            candidate = mix(result.text, color, weight)
            if contrast_ratio(candidate, result.panel) < 3.0:
                continue
            result.text = candidate
        elif key == "border":
            candidate = mix(result.border, color, weight)
            if contrast_ratio(candidate, result.panel) < 1.1:
                continue
            result.border = candidate
        elif key == "accent":
            candidate = mix(result.accent, color, weight)
            if contrast_ratio(candidate, result.panel) < 1.8:
                candidate = (
                    lighten(candidate, 0.25)
                    if luminance(result.panel) < 0.45
                    else darken(candidate, 0.2)
                )
            result.accent = candidate
        else:
            setattr(result, key, mix(getattr(result, key), color, weight))
        changed = True
    if changed:
        result.palettes = default_palettes(result)
        result.edge = mix(result.text_dim, result.text, 0.35)
        result.edge_choice = mix(result.accent, result.text, 0.18)
        result.edge_condition = mix(result.border, "#6f9bb3", 0.45)
        result.edge_call = mix(result.border, "#b39a6a", 0.55)
        result.button_fill = mix(result.panel, result.accent, 0.16)
        result.button_hover = mix(result.panel, result.accent, 0.32)
        result.button_text = result.text
        result.close_text = result.text_dim
    if vision.geometry:
        if "corner_radius" in vision.geometry:
            result.corner_radius = vision.geometry["corner_radius"]
        if "border_width" in vision.geometry:
            result.border_width = vision.geometry["border_width"]
    result.name = tokens.name + "_vision"
    result.source = tokens.source + "+vision"
    result.confidence = min(1.0, max(tokens.confidence, vision.confidence))
    result.notes = list(tokens.notes)
    result.notes.append(
        f"vision {vision.model or 'model'} confidence {vision.confidence:.2f}; "
        f"blend weight {weight:.2f}"
    )
    for note in vision.notes:
        result.notes.append("vision: " + note)
    return result


def vision_tokens(
    vision: VisionStyle,
    *,
    preset: str = "paper_dark",
    base: StyleTokens | None = None,
) -> StyleTokens:
    """Build tokens from a vision result alone (the screenshot style chain)."""

    return fuse_vision(base or preset_tokens(preset), vision, weight=0.75)
