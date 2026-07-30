import io
import unittest

from PIL import Image

from services.branding import BrandingError, normalize_logo


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


if __name__ == "__main__":
    unittest.main()
