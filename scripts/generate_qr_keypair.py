#!/usr/bin/env python
"""
TOUPAC — Génère une paire de clés RS256 pour la signature des QR de billets.

Script utilitaire volontairement en dehors de manage.py : une commande
`manage.py generate_keys` tapée par réflexe dans un shell de prod pourrait
écraser la clé en cours d'usage. Ici il faut viser explicitement un
répertoire et copier la clé privée en variable d'environnement soi-même.

Usage :
    python scripts/generate_qr_keypair.py --out-dir ./secrets/
"""
import argparse
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEY_SIZE_BITS = 2048


def generate_keypair(out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE_BITS)

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        # Non chiffrée : le chiffrement au repos est le rôle du secret
        # manager (Vault, SSM, etc.), pas de ce script.
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_path = out_dir / "qr_private.pem"
    public_path = out_dir / "qr_public.pem"
    private_path.write_bytes(private_pem)
    public_path.write_bytes(public_pem)

    return private_path, public_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir", required=True, type=Path,
        help="Répertoire de sortie (créé si absent). NE PAS pointer vers un répertoire versionné.",
    )
    args = parser.parse_args()

    private_path, public_path = generate_keypair(args.out_dir)

    print(f"Clé privée : {private_path}")
    print(f"Clé publique : {public_path}")
    print()
    print("Prochaine étape :")
    print("  Copier le contenu de qr_private.pem dans la variable d'env")
    print("  TOUPAC_QR_PRIVATE_KEY_PEM (multi-lignes).")
    print()
    print("  NE JAMAIS committer qr_private.pem.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
