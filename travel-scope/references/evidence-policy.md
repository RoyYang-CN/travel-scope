# 实体与动态信息证据规则（v4.0.5）

搜索页只能用于发现候选，不能证明一个 POI、班次或价格。Live dataset 除阅读用的 `source_evidence` 外，必须提供机器可审计的 `source_evidence_meta`。

每条记录至少包含 `evidence_id`、`destination`、`name`、`url`、`source_provider`、`evidence_level`、`verification_status`、`checked_at` 和 `supports`。

证据等级：

- `direct_entity`：官方实体页、官方目录中的实体详情页，或能够唯一识别该实体的权威详情页；严禁使用如 `/entity/\d+` 等程序化拼接的伪造合成 URL；
- `direct_schedule`：对应运营方、线路与有效期的具体时刻表页面/PDF；
- `official_area_reference`：官方目的地区域资料，只能支撑区域背景；
- `search_candidate`：搜索或聚合候选，不得计入正式覆盖率。

通用主页、搜索结果、带 `q/query/keyword/search` 的搜索 URL，不能算 `direct_entity`。交通出现具体班次时，必须有 `direct_schedule`、有效期和核验日期；未来班次未发布时保持 `future_unpublished`，不可拿旧班次改年份。

## §17 补充：每条 evidence 的最小字段（地图与非地图一律适用）

`source_type / source_url_or_ref / retrieved_at / supported_fields / lineage_group / content_digest / usage_scope / status`。
缺任一字段即 `status=INCOMPLETE`，该证据不得支撑任何 `identity_status=VERIFIED`（§17.3.1）。

**不能作为证据**（`evidence_ineligible_sources`）：站点通用首页、搜索结果页或搜索摘要、
**本项目自己生成的地图 URL**、以及任何经 Google Maps 抓取得来的内容。
`source_url == google_url` / `source_url == apple_url` 属自证循环，必须显式降级并写 reason code，
不得计入 `VERIFIED` 分子（§17.5.1）。

**来源独立性**：Nominatim、Photon、Overpass 与其他 OSM 镜像若指向同一个 OSM 对象，只算**一个血缘组**
（`lineage_group`）。三份同源结果不得记成"三方交叉验证"（§17.3.2）。裁决时：

- 硬冲突优先——国家/岛屿/目的地区域、分店、类别、航站楼/客运终端/集合点、坐标系与所需位置角色的
  明确冲突直接进 `CONFLICT`；名称高相似度或总分**不得**覆盖硬冲突（§17.3.4）。
- 缺失不等于匹配——名称、地址、坐标、类别或入口角色缺失必须单列，候选排序不得把缺失当作一致，
  也不得默认取第一候选（§17.3.5）。

**网络来源批准清单**（§17.3.9）：任何可访问域名必须先进入版本化的批准清单，记用途、速率、缓存权利与
robots/条款检查结果；公共 Nominatim、Photon demo、Overpass 公共实例**不得默认成为生产依赖**。
"来源不可达"与"查无实体"必须分开记录（`SOURCE_ERROR` ≠ `NO_RESULT`），禁止无限重试、代理绕过或悄悄换供应商。

**v4.2.2 具名搜索不是身份证据**：`NAMED_SEARCH` 的 URL 由选择器按 §6.1 的有来源字段拼出，
它证明“我们能用登记过的名字发起一次搜索”，不证明地点身份、不证明 Google 会落到该实体，
也不得据此把 `identity_status` 写成 `VERIFIED` 或把 `google_resolution_status` 写成非 `NOT_OBSERVED`。
反过来，`PUBLISHER_ENTITY_LINK` 必须有发布方实体页与声明链接两条独立资格，且出处主机命中已登记 adapter；
搜索页、根页、纯坐标页与本项目自己生成的 URL 仍然一律不算凭据（§17.3.1/§17.3.3 继续有效）。

**开放数据许可与署名**（§17.3.8）：OSM/extract 须记来源 URL、下载时间、版本/时间戳、SHA-256、ODbL/署名要求
与派生数据边界；读者成品、review/audit 产物与本地数据库的署名处理由本节与 renderer contract 明确，
不能只在实验日志里留一句来源。

**正式存储**（§17.3.7）：候选、证据、裁决、缓存哨兵与规则版本进入项目正式数据库；`.temp/` 只放一次性实验材料，
不得成为正式依赖。缓存必须区分 `NO_RESULT / SOURCE_ERROR / RATE_LIMITED / AMBIGUOUS / CONFLICT`。

研究深度是证据质量和复核深度，不只是条目数量：

- 精简：每个实体至少 1 个直达来源，完成路线关键事实研究；
- 标准：每个实体至少 1 个直达来源，动态事实另行核验并留痕；
- 深度：每个实体至少 2 个独立直达来源，并逐实体记录 `cross_source_review: pass`。
