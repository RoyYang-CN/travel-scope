# 地图目标：旧字段 → 四维状态迁移说明（v4.2.1 §17.2.7 / W1）

本文件是 W1 合同层的一部分。迁移的目的不是"改字段名"，而是**拆开一个字段同时冒充四件事**的旧模型：
`target_level` 既被当身份、又被当坐标质量、又被当链接类型、还被当"Google 已核验"。
跨版本失实声明（v4.1.9「地图跳转已交付」、v4.2.0「100% Place ID」）都来自这种混读。

## 1. 逐值映射（只允许"记录"，不允许"推断"）

| 旧 `target_level` | 出现量（冻结输入实测） | 允许迁移到 | 必须同时记录 | 禁止迁移到 |
| --- | --- | --- | --- | --- |
| `verified_platform_url` | PH 0 / CA 0 | `link_mode=PUBLISHER_ENTITY_LINK`（仅当证据是发布方实体页） | `reason_code=LEGACY_PLATFORM_URL`、原值保留 | `identity_status=VERIFIED`、`google_resolution_status=CORRECT_ENTITY` |
| `verified_place_id` | PH 0 / CA 0 | 不产生任何四维值；ID 本身按 `place_id_policy` 隔离审查 | `reason_code=LEGACY_PLACE_ID`、`quarantine_reason` | 任何 `identity_status` 提升；"覆盖率分子" |
| `verified_coordinate` | **PH 198/198、CA 205/205（全部）** | `coordinate_status` 待重新判定（默认 `UNVERIFIED`，除非坐标有独立来源） | `reason_code=LEGACY_COORDINATE_ONLY` | `identity_status=VERIFIED`（坐标档位从不证明身份） |
| `unnamed_coordinate` | PH 0 / CA 0 | `entity_type=coordinate_landmark` 且 `link_mode=COORDINATE` 或 `NONE` | `reason_code=LEGACY_UNNAMED` | 命名实体沿用；`identity_status=VERIFIED` |
| `search_candidate` | PH 0 / CA 0 | `link_mode=NAMED_SEARCH`（非关键目标）或 `NONE` | `reason_code=LEGACY_SEARCH_CANDIDATE` | `VERIFIED`、`PUBLISHER_ENTITY_LINK` |

旧 `verification_status`（`verified / pending / candidate / pending_visual_review`）一律映射为
`identity_status=UNVERIFIED` **加** 原值留档，除非该目标重新取得 §17.3.1 合格证据。
理由：`verified` 从不携带规则版本或证据引用，无法证明它当初是怎么得出的。

## 2. 禁止的自动映射（门禁逐条断言，见 `data-model.json.legacy_migration.forbidden_auto_mappings`）

1. `target_level=verified_coordinate → identity_status=VERIFIED`
2. `target_level=verified_place_id → identity_status=VERIFIED`
3. `verification_status=verified → identity_status=VERIFIED`
4. 任何状态 → `google_resolution_status=CORRECT_ENTITY`（只有独立观察能写，且须记环境与时间）
5. `URL 构造成功 → coordinate_status=VERIFIED`
6. `source_url 非空 → evidence.status=VERIFIED`
7. 名称高相似度 / 总分 → 覆盖硬冲突（§17.3.4）

## 3. 迁移必须留下的东西

每条 target 的 `migration` 对象：`{from: {原字段: 原值}, reason_code: "...", migrated_at: "...", policy_version: "..."}`。
无 reason code 的改写视为"就地无痕改写"，W2 直接判 FAIL。

## 4. 冻结输入的实测起点（不是估算，来自 W1 输入画像）

`map_targets` 在两份冻结输入里的真实形状：

| 项 | PH v4.1.9（198） | CA v4.2.0（205） |
| --- | --- | --- |
| `target_level` | `verified_coordinate` 198/198（100% 单一值） | `verified_coordinate` 205/205 |
| `verification_status` | `verified` 198/198 | `verified` 205/205 |
| `entity_type` | `named_entity` 198/198 | `named_entity` 205/205 |
| §17.2.5 的 19 个必填字段中已存在 | **1 / 19**（只有 `entity_type`） | **1 / 19** |
| `category` / `criticality` / `required_location_role` / `names` / `country_code` / 四维状态 | **字段不存在（0/198）** | **字段不存在（0/205）** |
| `google_place_id` 有值 | **0/198** | **0/205** |
| 链接形状 | `named_search_query` **198/198**（0 实体页、0 纯坐标） | `named_search_query` 205/205 |
| `source_url == google_url`（自证循环） | **0/198** | **205/205（全部）** |
| `coords` 可解析 / 为已知默认值 | 198/198 可解析，0 个默认值 | 205/205 可解析，0 个默认值 |
| `canonical_name` 含汉字（不能直接进 URL） | **111/198 = 56%** | 0/205 |
| `canonical_name` 去重率 | 198/198 | **50/205 = 24%**（同实体中英双卡的来源） |
| `qa_evidence` 形态 | **198/198 是纯字符串**，不是结构化证据 | 205/205 纯字符串 |

三条必须写在合同里的结论：

1. **四维字段几乎全部需要新建**，且 198/198 的链接其实都是"名称搜索"这一种——旧模型用
   `verified_coordinate` 给它们全部记了"已核验"，而 `google_place_id` 为 0。这说明旧 `VERIFIED_LEVELS`
   口径下的"已核验"从未包含身份核验，迁移时**不得**把它读成通过。
2. **Phase 1 用 PH 输入**：它没有自证循环问题（0/198），但有 111/198 汉字名——`names[]` 的拉丁名获取
   是 W3 resolver 的真实工作量，而不是渲染层问题。
3. **CA 输入的 205/205 全部自证**，正是 §17.5.1 的系统级 FAIL 样本；它同时说明现行
   `formal_data_gate` 对这一类的上报数（实测 seal_run 51–56 条）**少于**输入真实值，
   属门禁覆盖面缺口，W5 必须用总数扫描断言而不是首中即停。

证据：`.temp/v421_map_phase1/W1_contract/input_profile.json`（含逐字段覆盖率与 SHA-256）。

## 5. SKILL / VERSION 待并入段落（W8 正式同步，W1 先出草稿）

- SKILL 规则段（草稿）：地图交付的承诺范围改为"可审计的身份/位置证据 + 显式链接类型 + `NOT_OBSERVED` 默认"；
  删除"必须有真实 `ChIJ` Place ID"「浏览器核验落点/保存落点截图」「付费 Places 可在另行授权后使用」三类表述；
  新增四维枚举、`link_mode` 到按钮文案的映射、以及 §17.5.1 系统级 FAIL 清单。
- VERSION 段（草稿）：撤回 v4.2.0「100% 使用官方英文名与 `query_place_id`」与「确保 Google 商户卡直达」，
  改为本版实测口径：Place ID 0/198 与 0/205 为历史事实，本版不再以 Place ID 作为成绩或门槛。
- 两处草稿在 W8 前不落盘到 `SKILL.md` / `VERSION.md`，避免"文档先行于实现"。
