# Local Apps Verification Policy (在地工具研究与核验规范)

Travel-Scope v4.0.12 引入了在地工具（`local_apps`）作为独立一级导航与全渠道产物模块。

## 1. 核心目标与防欺骗原则
- **拒绝僵尸应用**：严禁推荐已停运、已下架、牌照被吊销或已合并退役的应用（如 Foodpanda Thailand 必须标记为 `retired` 并进入排除记录，不得进入正式推荐）。
- **拒绝非官方分发**：所有链接必须指向应用官方域名（如 `grab.com`）、Apple App Store 官方深链或 Google Play 官方页面。严禁使用第三方 APK 镜像站、网盘、搜索结果页或中介跳转推广链接。
- **拒绝费用脑补**：不展示未经核验的固定车费、起步价或外卖运费。费用仅使用“实时动态计价”、“偏远地区车辆稀少加收调度费”等定性说明。
- **拒绝盲目扩大覆盖**：若应用仅在曼谷或特定城市可用，必须标记为 `coverage_status: "city_specific"` / `destinations: ["Bangkok"]`，严禁标注为全国适用。
- **条件可用必挂风险**：若应用因海外信用卡 3DS 验证失败率高、必须当地手机号收验证码、或牌照处于整改期（如 Bolt），必须标记为 `conditional` 并明确填写 `limitations_cn` 与 `limitations_en`。

## 2. 状态机模型
- `verified_active`: 官方确认正常运营中，进入正式“出发前建议装好”或“推荐安装”。
- `conditional`: 存在使用门槛、支付限制或牌照审查，必须强制展示警示说明。
- `regional`: 仅特定城市支线适用。
- `pending`: 证据不足，仅留存研究底稿，禁入正式交付版。
- `retired`: 已停止服务，只留存于排除记录。

## 3. 时效门禁
- 叫车、外卖、支付类（`mobility_app`）：核验周期 <= 30 天。
- 城市交通、实用工具类（`utility_app`）：核验周期 <= 90 天。
- 官方旅游、紧急服务类（`official_service`）：核验周期 <= 180 天。
- `verified_at` 晚于生成日期时一票否决；超期自动降为 `pending`。
