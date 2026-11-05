from data_model import validate_records


def main() -> None:
    valid = [{"record_id": "hotel:1", "kind": "hotel", "destination": "A", "name": "Hotel", "coords": "1,2", "source_status": "verified", "image_refs": ["a", "b"]}]
    assert validate_records(valid) == []
    invalid = dict(valid[0], kind="unknown", coords="")
    errors = validate_records([invalid])
    assert any("invalid kind" in error for error in errors)
    assert any("missing" in error for error in errors)
    print("data model tests passed")


if __name__ == "__main__":
    main()
