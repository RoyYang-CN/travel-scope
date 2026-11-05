# 目的地画像

每个正式 run 在全国发现前建立 `manifest.destination_profile`，用于表达国家、地区和城市之间真实存在的结构差异。它不是国家模板，也不能预填旅游结论。

最小字段：

```json
{
  "scope_type": "country",
  "geography": ["continental", "islands"],
  "mobility_modes": ["rail", "road", "ferry", "flight"],
  "map_region": "international",
  "candidate_pool_count": 12,
  "coverage_boundary": "全国主要网关、文化腹地、自然区和海岸走廊",
  "data_availability": {"official_timetables": "mixed", "reusable_media": "mixed"},
  "uncertainties": [{"topic": "seasonal ferry", "impact": "route", "action": "recheck before booking"}]
}
```

`scope_type` 使用 `country`、`custom_area` 或 `city`；`map_region` 只能为 `international` 或 `mainland_china`。候选池低于当前 Q7 目标时，必须增加具体的 `candidate_pool_exception`，说明面积、目的地数量、可达性或证据边界，不能用重复小区域凑数。

画像决定要研究哪些交通、媒体和活动模块，但不得降低以下共同门禁：来源真实性、路线连续性、地图身份、Q0-Q8 留痕、未来班次诚实状态和五类输出同源。
