"""Regression checks for CN/EN Excel delivery fields and translation guards."""

import gen_travel_scope as gen


def main() -> None:
    required_headers = {
        "Google图片1": "Google Image 1",
        "Google图片2": "Google Image 2",
        "Google Place ID": "Google Place ID",
        "经纬度(WGS84)": "Coordinates (WGS84)",
        "出发节点": "Origin Node",
        "到达节点": "Arrival Node",
        "是否需预约": "Reservation Required",
        "是否适合自驾": "Suitable for Self-drive",
        "特殊风险": "Special Risks",
    }
    for chinese, english in required_headers.items():
        assert gen.HEADER_EN.get(chinese) == english, (chinese, gen.HEADER_EN.get(chinese))
    assert gen.SHEET_EN["交通信息"] == "Transport"
    assert gen.SHEET_EN["核心体验"] == "Key Experiences"
    assert gen.SHEET_EN["当地连锁与便捷选择"] == "Local Chains & Convenience"
    assert gen.SHEET_EN["行前准备"] == "Pre-trip Checklist"
    assert gen.SHEET_EN["当地旅行要点"] == "Local Travel Essentials"

    original = gen.OUTPUT_LANG
    try:
        gen.OUTPUT_LANG = "en"
        rows = {"destinations": [["示例城市", "Demo City", "History & culture", "3 days"]]}
        gen.assert_english_excel_rows(rows)
        try:
            gen.assert_english_excel_rows({"destinations": [["示例城市", "Demo City", "历史文化", "3 days"]]})
        except ValueError:
            pass
        else:
            raise AssertionError("untranslated EN dynamic Excel cell was not blocked")
    finally:
        gen.OUTPUT_LANG = original
    print("excel contract tests passed")


if __name__ == "__main__":
    main()
