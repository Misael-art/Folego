from folego.safely import hashing


def test_sha256_bytes_matches_known_digest():
    assert hashing.sha256_bytes(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_sha256_file_matches_digest_of_content(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello")
    assert hashing.sha256_file(p) == hashing.sha256_bytes(b"hello")


def test_read_hashed_returns_bytes_and_digest(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"deck")
    data, digest = hashing.read_hashed(p)
    assert data == b"deck"
    assert digest == hashing.sha256_bytes(b"deck")
