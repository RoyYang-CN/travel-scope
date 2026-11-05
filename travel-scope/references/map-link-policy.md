# 地图跳转规则（v5.0.0）

v5.0.0 现行发布身份继承 v4.2.2 地图合同（V4.2.2_ITERATION_CHECKLIST.md 仍是该功能合同的历史权威）。本次只迁移产品发布身份，不改变四态地图语义。标题随当前发布身份更新，由 `test_v419_regressions.test_version_alignment_v419` 与版本策略/封存清单共同钉住。

地图按钮承诺的是**可审计的地点身份/位置证据与显式链接类型**，不承诺 Google 的实际解析结果。
本节优先级高于旧版任何"Place ID 百分比""必须核验落点"的表述；权威枚举在
`references/data-model.json`，渲染判据在 `references/renderer-contract.json.presentation.map_link_contract`。

## 1. 四维状态（互不替代，禁止相互推导）

| 维度 | 字段 | 枚举 | 说明 |
| --- | --- | --- | --- |
| 身份 | `identity_status` | `UNVERIFIED / VERIFIED / AMBIGUOUS / CONFLICT / UNRESOLVED / STALE` | `VERIFIED` 必须引用规则版本与独立证据；不等于绝对真实，更不等于 Google 已核验 |
| 坐标 | `coordinate_status` | `MISSING / UNVERIFIED / VERIFIED / CONFLICT / STALE` | 同时记 WGS84/经纬顺序/来源/精度/`location_role`；缺失写 `MISSING`，**不得**填 0 或城市默认中心 |
| 链接 | `link_mode` | `PUBLISHER_ENTITY_LINK / NAMED_SEARCH / COORDINATE / NONE` | 必须记 provider、URL 构造版本与选择原因 |
| Google 观察 | `google_resolution_status` | `NOT_OBSERVED / CORRECT_ENTITY / MULTIPLE_RESULTS / WRONG_ENTITY / NO_RESULT / BLOCKED / STALE` | 正式自动链默认 `NOT_OBSERVED`；只有独立研发观察才能改值 |

`NOT_OBSERVED` 是合法的事实状态，**不得自动晋级**（§17.1.6）。旧 `target_level` / `verification_status` /
`verified_coordinate` 只允许兼容读取，且迁移必须保留原值与 reason code（§17.2.7、见
`references/map-contract-migration.md`）。

## 2. 四种按钮（读者可见文案必须与链接类型一致）

| `link_mode` | 中文 | English | 允许条件 |
| --- | --- | --- | --- |
| `PUBLISHER_ENTITY_LINK` | 在 Google Maps 查看地点 | View on Google Maps | 地点/运营方页面明确发布了该链接；**只证明发布方提供过**，不证明当前地址、入口坐标或永久正确（§17.3.3） |
| `NAMED_SEARCH` | 在 Google Maps 搜索此地点 | Search this place in Google Maps | `query=NAME, ADDRESS/DESTINATION, COUNTRY` 的官方无密钥 URL；URL 构造成功 ≠ 地点被验证 |
| `COORDINATE` | 查看坐标位置 | View coordinate location | 仅 `coordinate_landmark + coordinate_status=VERIFIED`；**命名实体永不显示纯坐标按钮** |
| `NONE` | （不渲染按钮） | （no button） | 可显示有来源的名称/地址与"地图未解析"说明；**不得**再造一个会落到城市/州界的次级搜索来绕过状态 |

禁止出现的文案：`已由 Google 核验` / `Verified by Google` / `保证直达` / `guaranteed match`。
每个按钮必须带 `data-target-id / data-entity-type / data-identity-status / data-coordinate-status /
data-link-mode / data-google-resolution-status`，且 dataset、DOM、门禁报告三处取值必须一致。

各 provider 的链接状态互相独立：Google 的实体链接不得把 Apple 或 OSM 升级为实体直达（§17.4.5）。

## 3. Place ID 的现行地位

Place ID 是**可选外部 ID**：不是必填字段、不是覆盖率指标、不是发布门槛（§17.1.5）。
不存在"≥90% Place ID"或"0 Place ID 即失败"。无来源、合成、或仅凭正则形状通过校验的 ID 一律隔离，
并计入 `quarantined_identifiers` 报告项。`ChIJ` 形状检查只用于**发现合成串**，不得反过来当作核验凭据。

## 4. 硬边界（违反即整批阻断）

- **零 Google Billing/API/Key**：正式代码、配置、ENV 合同、生成命令与文档不得启用 Places/Geocoding/Maps JS，
  也不得因"ID-only 当前零价格"而启用；`--google-maps-key`、`TRAVEL_SCOPE_GOOGLE_PLACES_KEY` 等入口须移除或硬阻断。
- **零 Google Maps 抓取**：不得用浏览器、headless、HTTP 或 DOM 解析批量采集实体、Place ID、名称、地址、坐标、
  评价或跳转；不得绕过验证码、登录墙或限流。
- **零隐藏兜底**：来源故障、开放数据未命中、缓存过期或关键字段缺失，只能进入显式失败/降级状态；
  不得切到付费 API、试用额度、个人 Key 或任何需承担超额责任的通道。
- **零自证循环**：本项目自己生成的地图 URL 不能作为证据；`source_url == google_url`（或等于 `apple_url`）
  即显式降级并记 reason code，不得计入任何 `VERIFIED` 分子。
- **零字符级改名**：名称只判"可用/不可用"。出现汉字、纯数字残留（`39`、`518`）或
  `… Venue|Location|Place|Point|Spot` 模板串即不可用；不可用**不得**被删字后写进 URL。

v4.2.2 修订（业主 2026-10-29 依清册 §4 禁止动作第 2 条「不删除中文/本地文字后猜英文名；
没有可信英文名时保留有来源的本地正式名称」放开）：**本地正式名称可以进入境外搜索串**，
reason code `SELECTED_NAMED_SEARCH_LOCAL_NAME_RATIFIED` 单独计数（登记在
`map-link-selection.json::query_rules.local_name_query_ratified_by`，登记为空则配置加载即报错）。
上面那条硬边界的**主体没有放松**：不可用名称仍然只能降级为 `NONE`，
`… Venue|Location|Place|Point|Spot` 模板串、纯数字残片（`39`、`518`）、走廊串一律拒绝。
**残片名一律不得作为查询名**：英文名如果整体是括号片段（如 `(Union Station)`）或等于本地名去掉
CJK 后的字母数字残片，判为删字残留，reason code 走单独一条 `SELECTED_NAMED_SEARCH_LOCAL_NAME_AFTER_RESIDUE`
并改用有来源的本地正式名称——拒绝的是那个残片，不是砍掉按钮；两种本地名搜索在报告里分开计数，
因为「本来没有英文名」与「英文名是删出来的」（V0-L02/V0-L06）是两回事。
URL 用普通 percent-encoding 原样承载本地文字，不得删除任何字符。
海外地图 URL 含汉字自 v4.2.2 起不再是地图错误（`MAP_HREF_CJK` 改为只查「URL 里的本地文字
必须是该 target 有来源名称的原文」）；**英文 UI 可见文字泄漏是独立门禁，不因此放松**。

门禁报告必须输出四项计数且全部为 0：`google_billable_api_calls`、`google_api_keys_used`、
`google_maps_scrape_attempts`、`paid_fallback_attempts`（§17.5.5）。日志只报变量名与计数，不报凭据值。

## 4b. v4.2.2 链接选择状态机与文案（ACCEPTED，产品承诺已降级）

唯一配置：`references/map-link-selection.json`（`selection_version = v422-link-selection-1`）；
唯一实现：`scripts/map_link_selector.py::select`。渲染层与 DOM 门禁只消费它的输出，
不得再拼 URL、判主机或猜名称（§9）。reason code 的唯一登记处是配置里的 `reason_codes` 闭集，
唯一生效处是状态机的 `then` / `reason_code_overrides`；配置别处再写 `reason_code` 字段
（V1 前 `name_residue_rules`、`join_ambiguity_signals` 各有一份无人读取的副本）或登记状态机
走不到的 code（报告里永远为 0 的假可观测项），配置加载即报错。

1. 已知错链/硬冲突（`WRONG_ENTITY`、`CONFLICT`、隔离标记）⇒ `NONE`，旧 URL 进 `isolated_link_url`。
2. 合格发布方实体链（证据行资格、URL 形态、provider 一致、出处本身是发布方实体页四条独立条件全过）⇒ `PUBLISHER_ENTITY_LINK`。
3. 无标准名称的坐标地标且坐标 `VERIFIED` ⇒ `COORDINATE`。
4. 命名实体有可用拉丁名称、身份属 `UNVERIFIED/AMBIGUOUS/UNRESOLVED/VERIFIED`、观察状态不阻断 ⇒ `NAMED_SEARCH`。
4b. 命名实体只有有来源的本地正式名称（无英文名，或英文名被判定为删字/括号残片）⇒ `NAMED_SEARCH`，本地名原样 percent-encoding 进串，文案与提示与第 4 条完全相同（§4 line 102，业主 2026-10-29 登记）。残片降级另记 `SELECTED_NAMED_SEARCH_LOCAL_NAME_AFTER_RESIDUE`。
5. 名称是占位/数字残片/走廊串或缺失、身份 `STALE`、已有观察为 `NO_RESULT/BLOCKED/STALE` ⇒ `NONE`。

按钮文案（与 `references/renderer-contract.json` 逐字一致）：`NAMED_SEARCH` 中文必须是
「在 Google Maps 搜索此地点（落点未核验）」、英文 `Search this place in Google Maps (landing not verified)`；
关键目标另加「地图落点未核验，请以订单、票证或运营方公布的地址、航站楼/码头信息为准。」；
带模糊连接信号者另加「可能有多个结果，请核对订单、票证或运营方信息。」

具名搜索 URL 的生成**永远不得**改写 `identity_status` / `coordinate_status` /
`google_resolution_status`；除 `PUBLISHER_ENTITY_LINK` 外一律保持 `NOT_OBSERVED`，除非存在独立观察记录。
Google 实体卡片命中率固定报告为 `NOT MEASURED / NOT A RELEASE GATE`。
## 5. 具名实体与坐标地标的边界

酒店、餐厅、咖啡馆、景点、潜店、机场、航站楼、码头、客运终端、车站、集合点一律 `named_entity`（§17.2.6）。
只有现实中确实没有标准名称的自然观测点/坐标点才可以是 `coordinate_landmark`。
交通端点必须逐一绑定机场、港口、车站、码头或上车点；`A→B` 线路名、泛化的"码头"、运营商主页都不是地图实体。
中国大陆交付物仍只用高德/百度，不得暴露 Google 链接。

## 6. 失败范围（不做"一损俱损"，也不做"蒙混过关"）

- **系统级 FAIL**：出现 Google 调用/抓取、合成外部 ID、自证循环、默认坐标、字符级删名、四维字段缺失、
  状态与 DOM/URL 不一致、隐藏成功 fallback（§17.5.1）。
- **关键业务 FAIL**：`criticality=CRITICAL_ITINERARY`（实际入住、登机、登船、换乘、集合）的
  `identity_status != VERIFIED` 或所需 `required_location_role`/坐标证据不满足 → 阻断相关行程段；
  若删段使攻略不可执行则整份阻断（§17.5.2）。
- **非关键局部降级**：普通餐饮、咖啡馆与备选点可为 `NAMED_SEARCH` 或 `NONE`，报告须计数并列名，
  不因少量缺失拖垮整份攻略，也**不得**计入 `VERIFIED` 分子（§17.5.3）。
- **已知错链零容忍**：任何已知 `WRONG_ENTITY`、跨城市/跨岛、州级回落、错误分店或错误入口的链接必须
  删除或隔离；改标签不能把已知错链变成可交付搜索链接（§17.5.4）。

## 7. 历史回归（本规则要防的事）

v4.1.9 记"Universal Search 地图跳转已交付"、v4.2.0 记"100% Place ID"，实际是名称搜索与合成串；
v4.2.0 生成器用"删汉字兜底"制造了 151 条 `California Venue`；v4.2.1 实测同一成品 `google_place_id` **0/205**。
这三件事的共同根因是**用单一 `target_level` 同时表达身份、坐标、链接与观察**，因此本版改为四维独立状态，
并禁止任何"由 A 推 B"的自动晋级。
