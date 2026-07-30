import io
import unittest
from unittest.mock import patch

from PIL import Image

from services.branding import BrandingError, BrandingStorageError, normalize_logo, replace_logo


class BrandingTests(unittest.TestCase):
    def test_logo_is_resized_and_normalized_to_webp(self) -> None:
        source = io.BytesIO()
        Image.new("RGBA", (900, 300), (20, 40, 60, 128)).save(source, "PNG")

        normalized = normalize_logo(source.getvalue(), "image/png")

        with Image.open(io.BytesIO(normalized)) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertLessEqual(image.width, 512)
            self.assertLessEqual(image.height, 512)

    def test_invalid_image_is_rejected(self) -> None:
        with self.assertRaises(BrandingError):
            normalize_logo(b"not an image", "image/png")

    def test_oversize_logo_is_rejected_before_decode(self) -> None:
        with self.assertRaises(BrandingError):
            normalize_logo(b"x" * (2 * 1024 * 1024 + 1), "image/png")

    def test_storage_failure_is_reported_as_branding_storage_error(self) -> None:
        source = io.BytesIO()
        Image.new("RGB", (32, 32), "white").save(source, "PNG")

        with patch("services.branding.get_branding_path", return_value=None), patch(
            "services.branding.upload_branding_asset",
            side_effect=RuntimeError("storage unavailable"),
        ):
            with self.assertRaises(BrandingStorageError):
                replace_logo(source.getvalue(), "image/png")


if __name__ == "__main__":
    unittest.main()
