"""Regression tests for optional content-module completeness gates."""

import gen_travel_scope as gen


def main() -> None:
    original = (gen.WORTH_IT, gen.LOCAL_CHAINS, gen.PACKING, gen.LOCAL_KNOWLEDGE)
    try:
        gen.WORTH_IT = [["A", "值得", "Worth", "Why", "Travellers", "2h", "Dry", "No", "Easy", "verified"]]
        gen.LOCAL_CHAINS = [["A", "品牌", "Brand", "Food", "Stable", "Quick meal", "10", "Airport", "verified"]]
        gen.PACKING = [["海岛", "防晒", "Sunscreen", "Buy", "Island", "Before", "Protect skin", "verified"]]
        gen.LOCAL_KNOWLEDGE = [
            ["天气", "Weather", "雨季", "Rainy season", "确认预报", "Check forecast", "verified"],
            ["文化礼仪", "Culture and etiquette", "着装", "Dress code", "确认当地要求", "Check local rules", "verified"],
            ["交通", "Transport", "班次、网络通信", "Schedules and network connectivity", "确认运营", "Check service", "verified"],
            ["支付换汇", "Payment and cash", "备用现金", "Keep cash", "确认支付方式", "Confirm payment", "verified"],
            ["安全", "Safety", "常见风险与紧急处理", "Common risks and emergency handling", "确认提醒", "Check alerts", "verified"],
        ]
        assert gen.validate_content_modules() == []
        gen.LOCAL_KNOWLEDGE = gen.LOCAL_KNOWLEDGE[1:]
        assert any("天气" in error for error in gen.validate_content_modules())
        gen.LOCAL_KNOWLEDGE = [
            ["天气", "Weather", "雨季", "Rainy season", "确认预报", "Check forecast", "verified"],
            ["文化礼仪", "Culture and etiquette", "着装", "Dress code", "确认当地要求", "Check local rules", "verified"],
            ["交通", "Transport", "班次、网络通信", "Schedules and network connectivity", "确认运营", "Check service", "verified"],
            ["支付换汇", "Payment and cash", "备用现金", "Keep cash", "确认支付方式", "Confirm payment", "verified"],
            ["安全", "Safety", "常见风险与紧急处理", "Common risks and emergency handling", "确认提醒", "Check alerts", "verified"],
        ]
        gen.PACKING[0][7] = "待核验"
        assert any("PACKING" in error for error in gen.validate_content_modules())
        print("content module tests passed")
    finally:
        gen.WORTH_IT, gen.LOCAL_CHAINS, gen.PACKING, gen.LOCAL_KNOWLEDGE = original


if __name__ == "__main__":
    main()
