import base64
import hashlib
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from updates import UpdateError, canonical_manifest, verify_manifest, version_tuple


class UpdateTests(unittest.TestCase):
    def test_signed_manifest_and_tamper_detection(self):
        private = Ed25519PrivateKey.generate()
        public = base64.urlsafe_b64encode(private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )).decode("ascii").rstrip("=")
        content = b"instalador de teste"
        manifest = {
            "version": "2.1.0",
            "installer_url": "https://updates.example/ConectaPC.exe",
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        }
        manifest["signature"] = base64.urlsafe_b64encode(
            private.sign(canonical_manifest(manifest))
        ).decode("ascii").rstrip("=")
        self.assertEqual(verify_manifest(manifest, public)["version"], "2.1.0")
        manifest["size"] += 1
        with self.assertRaises(UpdateError):
            verify_manifest(manifest, public)

    def test_version_comparison_is_numeric(self):
        self.assertGreater(version_tuple("2.10.0"), version_tuple("2.9.9"))


if __name__ == "__main__":
    unittest.main()
