from validate_output import validate_map_links


def test_valid_provider_links():
    html = """
    <a class="btn-map" href="https://www.google.com/maps/search/?api=1&amp;query=Example%20Museum%2C%20Example%20City"></a>
    <a class="btn-map" href="https://uri.amap.com/marker?position=116.4,39.9&amp;name=x"></a>
    <a class="btn-map" href="https://maps.apple.com/?q=x&amp;ll=39.9,116.4"></a>
    <a class="btn-map" href="https://api.map.baidu.com/marker?location=39.9,116.4&amp;title=x"></a>
    """
    errors = []
    validate_map_links(html, errors)
    assert not errors, errors


def test_invalid_google_coordinates_fail():
    html = '<a class="btn-map" href="https://www.google.com/maps/search/?api=1&amp;query=91,181"></a>'
    errors = []
    validate_map_links(html, errors)
    assert errors


def test_ambiguous_coordinate_only_google_target_fails():
    html = '<a class="btn-map" href="https://www.google.com/maps/search/?api=1&amp;query=39.9,116.4"></a>'
    errors = []
    validate_map_links(html, errors)
    assert any("只有坐标" in error for error in errors)


if __name__ == "__main__":
    test_valid_provider_links()
    test_invalid_google_coordinates_fail()
    test_ambiguous_coordinate_only_google_target_fails()
    print("navigation contract tests passed")
