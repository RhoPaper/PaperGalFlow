from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pgf_style import (
    OpenAICompatibleVision,
    VisionConfig,
    VisionError,
    fuse_vision,
    preset_tokens,
    vision_backend,
    vision_tokens,
)
from pgf_core.cli import _collect_screenshots
from pgf_core.errors import PgfError
from pgf_style.vision import parse_vision_payload

from .test_png import make_png


def png_bytes() -> bytes:
    return make_png(4, 4, [(240, 220, 240, 255)] * 16)


def response(content: object) -> bytes:
    text = content if isinstance(content, str) else json.dumps(content)
    return json.dumps({"choices": [{"message": {"content": text}}]}).encode()


class VisionConfigTests(unittest.TestCase):
    def test_environment_configuration(self) -> None:
        env = {
            "PGF_VISION_ENDPOINT": "https://example.test/v1",
            "PGF_VISION_MODEL": "vision-1",
            "PGF_VISION_API_KEY": "secret",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            config = VisionConfig.from_env()
            backend = vision_backend()
        self.assertTrue(config.configured)
        self.assertEqual(config.chat_url(), "https://example.test/v1/chat/completions")
        self.assertIsNotNone(backend)

    def test_unconfigured(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"PGF_VISION_ENDPOINT": "", "PGF_VISION_MODEL": "", "PGF_VISION_API_KEY": ""},
            clear=False,
        ):
            self.assertIsNone(vision_backend())
        config = VisionConfig(endpoint="", model="")
        self.assertFalse(config.configured)
        with self.assertRaises(VisionError):
            OpenAICompatibleVision(config)


class VisionClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.image = self.root / "shot.png"
        self.image.write_bytes(png_bytes())
        self.requests: list[dict] = []

    def transport(self, url, headers, body, timeout):
        self.requests.append(
            {"url": url, "headers": headers, "body": json.loads(body.decode()), "timeout": timeout}
        )
        return response(
            {
                "colors": {
                    "accent": "#ff6699",
                    "panel": "#fff0f5",
                    "text": "#33202a",
                    "border": "#eec0d0",
                },
                "geometry": {"corner_radius": 20, "border_width": 3},
                "confidence": 0.9,
                "notes": ["pastel dialogue box"],
            }
        )

    def backend(self) -> OpenAICompatibleVision:
        config = VisionConfig(
            endpoint="https://example.test/v1/chat/completions",
            model="vision-1",
            api_key="secret",
        )
        return OpenAICompatibleVision(config, transport=self.transport)

    def test_analyze_builds_data_url_and_parses_json(self) -> None:
        vision = self.backend().analyze([self.image])
        self.assertEqual(vision.colors["accent"], "#ff6699")
        self.assertEqual(vision.geometry["corner_radius"], 20)
        self.assertEqual(vision.confidence, 0.9)
        self.assertEqual(vision.model, "vision-1")
        self.assertEqual(len(self.requests), 1)
        request = self.requests[0]
        self.assertEqual(request["url"], "https://example.test/v1/chat/completions")
        self.assertEqual(request["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(request["body"]["model"], "vision-1")
        user_content = request["body"]["messages"][1]["content"]
        image_part = next(part for part in user_content if part["type"] == "image_url")
        self.assertTrue(image_part["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_accepts_fenced_markdown_and_list_content(self) -> None:
        def fenced(url, headers, body, timeout):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {
                                        "type": "text",
                                        "text": '```json\n{"colors": {"accent": "#336699"}, "confidence": 0.7}\n```',
                                    }
                                ]
                            }
                        }
                    ]
                }
            ).encode()

        backend = OpenAICompatibleVision(
            VisionConfig(endpoint="https://x.test/chat/completions", model="m"),
            transport=fenced,
        )
        vision = backend.analyze([self.image])
        self.assertEqual(vision.colors["accent"], "#336699")
        self.assertEqual(vision.confidence, 0.7)

    def test_multiple_images_and_limits(self) -> None:
        second = self.root / "shot2.png"
        second.write_bytes(png_bytes())
        vision = self.backend().analyze([self.image, second])
        self.assertTrue(vision.has_style)
        extras = []
        for index in range(3):
            path = self.root / f"extra{index}.png"
            path.write_bytes(png_bytes())
            extras.append(path)
        with self.assertRaises(VisionError):
            self.backend().analyze([self.image, second] + extras)

    def test_rejects_missing_and_unsupported_files(self) -> None:
        with self.assertRaises(VisionError):
            self.backend().analyze([self.root / "missing.png"])
        text = self.root / "shot.txt"
        text.write_text("x", encoding="utf-8")
        with self.assertRaises(VisionError):
            self.backend().analyze([text])
        with self.assertRaises(VisionError):
            self.backend().analyze([])

    def test_bad_responses(self) -> None:
        config = VisionConfig(endpoint="https://x.test/chat/completions", model="m")
        cases = [
            b"not json",
            json.dumps({"choices": []}).encode(),
            json.dumps({"choices": [{"message": {"content": "no json here"}}]}).encode(),
            json.dumps({"choices": [{"message": {"content": '{"colors": {}}'}}]}).encode(),
        ]
        for index, payload in enumerate(cases):
            backend = OpenAICompatibleVision(config, transport=lambda *args, **kwargs: payload)
            with self.assertRaises(VisionError, msg=index):
                backend.analyze([self.image])


class VisionFusionTests(unittest.TestCase):
    def vision(self) -> object:
        return parse_vision_payload(
            {
                "colors": {"panel": "#fff0f5", "accent": "#ff6699", "text": "#33202a"},
                "geometry": {"corner_radius": 20, "border_width": 3},
                "confidence": 0.8,
                "notes": ["pastel UI"],
            },
            model="vision-1",
        )

    def test_fusion_moves_colours_and_geometry(self) -> None:
        base = preset_tokens()
        base.confidence = 0.2
        fused = fuse_vision(base, self.vision())
        self.assertNotEqual(fused.panel, base.panel)
        self.assertNotEqual(fused.accent, base.accent)
        self.assertEqual(fused.corner_radius, 20)
        self.assertEqual(fused.border_width, 3)
        self.assertTrue(fused.source.endswith("+vision"))
        self.assertEqual(fused.palette("read").border, fused.accent)
        self.assertTrue(any("vision vision-1" in note for note in fused.notes))
        self.assertTrue(any("pastel UI" in note for note in fused.notes))

    def test_low_confidence_vision_has_smaller_weight(self) -> None:
        strong = parse_vision_payload(
            {"colors": {"panel": "#ffffff"}, "confidence": 1.0}, model="m"
        )
        weak = parse_vision_payload(
            {"colors": {"panel": "#ffffff"}, "confidence": 0.1}, model="m"
        )
        low_evidence = preset_tokens()
        low_evidence.confidence = 0.1
        high_evidence = preset_tokens()
        high_evidence.confidence = 0.9
        a = fuse_vision(low_evidence, strong)
        b = fuse_vision(high_evidence, strong)
        self.assertNotEqual(a.panel, b.panel)
        weak_result = fuse_vision(low_evidence, weak)
        self.assertNotEqual(weak_result.panel, a.panel)

    def test_text_is_kept_when_contrast_would_drop(self) -> None:
        base = preset_tokens()
        vision = parse_vision_payload(
            {"colors": {"text": "#111111", "panel": "#101010"}, "confidence": 1.0},
            model="m",
        )
        fused = fuse_vision(base, vision, weight=0.8)
        self.assertEqual(fused.text, base.text)

    def test_vision_only_tokens(self) -> None:
        tokens = vision_tokens(self.vision(), preset="paper_light")
        self.assertEqual(tokens.source, "preset+vision")
        self.assertEqual(tokens.corner_radius, 20)
        self.assertGreater(tokens.confidence, 0.7)


class ScreenshotCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.image = self.root / "shot.png"
        self.image.write_bytes(png_bytes())
        (self.root / "notes.txt").write_text("x", encoding="utf-8")

    def test_directory_expansion_dedup_and_order(self) -> None:
        second = self.root / "z.jpg"
        second.write_bytes(b"jpeg")
        paths = _collect_screenshots([str(self.root), str(self.image)])
        self.assertEqual(paths, (str(self.image.resolve()), str(second.resolve())))

    def test_missing_and_empty_directory(self) -> None:
        with self.assertRaises(PgfError):
            _collect_screenshots([str(self.root / "missing.png")])
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaises(PgfError):
            _collect_screenshots([str(empty)])
        self.assertEqual(_collect_screenshots(None), ())


if __name__ == "__main__":
    unittest.main()
