/* Travel-Scope v4.2.2 Single-Page Application (SPA) Engine */
(function(){
'use strict';
const D = JSON.parse(document.getElementById('dataset').textContent);

/* v4.2.1 SS5: every inlined bitmap ships exactly once in D.asset_blobs, keyed by the
   sha256 of the delivered bytes; dataset fields carry asset://sha256:<digest> instead of a
   second copy of the base64. v4.2.0 pasted the full blob at each use site, so the hero image
   cost 369KB twice on mobile first paint. */
const ASSET_REF_PREFIX = 'asset://sha256:';
const ASSET_BLOBS = D.asset_blobs || {};
function assetUrl(value){  if (typeof value !== 'string' || !value) return value || '';
  if (value.indexOf(ASSET_REF_PREFIX) === 0) return ASSET_BLOBS[value.slice(ASSET_REF_PREFIX.length)] || '';
  return value;
}
/* digest 反查：dataset 用 asset://sha256:<digest> 引用，渲染期解析成 data URI 后引用信息就没了。
   门禁要问「读者现在看到的这张图是哪份登记字节」，所以在这里把 URL→digest 的反表建一次；
   Map 只存引用，不复制 base64，内存代价是一个条目数。 */
const BLOB_DIGEST_BY_URL = (() => {
  const map = new Map();
  for (const [digest, url] of Object.entries(ASSET_BLOBS)) {
    if (!map.has(url)) map.set(url, digest);
  }
  return map;
})();
function assetDigestOf(value){
  if (typeof value !== 'string' || !value) return '';
  if (value.indexOf(ASSET_REF_PREFIX) === 0) return value.slice(ASSET_REF_PREFIX.length);
  return BLOB_DIGEST_BY_URL.get(value) || '';
}

/* §12 slot tiering: the build inlines the renditions a slot can actually use and lists them here.
   Without srcset a phone downloads the 1200px hero; with it the browser picks the 800px copy that
   is already in this same file, so the saving is real decode+memory, not network. */
function srcsetAttr(tiers){
  if (!Array.isArray(tiers) || tiers.length < 2) return '';
  const parts = tiers.map(t => {
    const url = assetUrl(t.ref || t);
    return (url && t.width) ? (url + ' ' + t.width + 'w') : '';
  }).filter(Boolean);
  return parts.length > 1 ? parts.join(', ') : '';
}
function applyTiers(imgEl, tiers, sizes){
  const set = srcsetAttr(tiers);
  if (set) { imgEl.setAttribute('srcset', set); imgEl.setAttribute('sizes', sizes || '100vw'); }
  return imgEl;
}


/* ---------- state ---------- */
const state = { lang:'cn', route:D.routes[0][0], tab:'overview' };
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

// 标准业态双语词典 (V4.2.0 升级: 彻底根除英文模式 POI 分类汉字裸奔)
const CATEGORY_DICT = {
  // 住宿分类
  '海景精品度假村': 'Seaview Boutique Resort',
  '悬崖独栋泳池别墅': 'Cliffside Pool Villa',
  '热带花园精品酒店': 'Tropical Garden Boutique Hotel',
  '生态海景潜水度假村': 'Eco Marine Dive Resort',
  '海滨木屋度假村': 'Beachfront Bungalow Resort',
  '豪华海滩度假村': 'Luxury Beach Resort',
  '极简现代设计酒店': 'Minimalist Design Hotel',
  '雨林悬崖生态庄园': 'Rainforest Cliff Eco Estate',
  '悬崖海景酒店': 'Cliffside Oceanfront Hotel',
  '精品设计酒店': 'Boutique Design Hotel',
  '奢华度假村': 'Luxury Resort',
  '海滩度假村': 'Beach Resort',
  '精品度假村': 'Boutique Resort',
  '度假酒店': 'Resort Hotel',
  '海滨度假酒店': 'Seaside Resort Hotel',
  '悬崖度假村': 'Cliff Resort',
  '商务与机场酒店': 'Airport & Business Hotel',
  '机场中转酒店': 'Airport Transit Hotel',
  '经典商务酒店': 'Classic Business Hotel',
  '海景奢华酒店': 'Luxury Oceanview Hotel',
  '历史遗产酒店': 'Historic Heritage Hotel',
  '山林野奢度假村': 'Mountain Wilderness Resort',
  '亲子度假酒店': 'Family Resort',
  '海边平价旅馆': 'Seaside Budget Inn',
  '青年旅舍与胶囊': 'Hostel & Capsule',
  '汽车旅馆': 'Motel',
  '传统经典': 'Heritage Classic',
  '经济实用': 'Budget Stay',
  '中档舒适': 'Midscale Comfort',
  '品质轻奢': 'Premium Upscale',
  '高端奢华': 'Luxury',
  // 餐饮美食
  '海鲜料理': 'Seafood Restaurant',
  '印尼风味料理': 'Indonesian Cuisine',
  '热带海景餐厅': 'Tropical Oceanview Dining',
  '悬崖日落酒吧': 'Cliff Sunset Bar',
  '海滨露天餐厅': 'Open-air Beachfront Restaurant',
  '健康轻食与有机素食': 'Organic & Healthy Dining',
  '法式小馆': 'French Bistro',
  '地中海风味餐厅': 'Mediterranean Restaurant',
  '加州特色料理': 'California Cuisine',
  '米其林推荐餐厅': 'Michelin Recommended Dining',
  '当地特色小吃': 'Local Street Food',
  '日式料理': 'Japanese Dining',
  '传统中餐': 'Traditional Chinese Dining',
  '美式牛排馆': 'American Steakhouse',
  '海边披萨酒吧': 'Beachside Pizza & Bar',
  '意式休闲小馆': 'Italian Trattoria',
  '精酿啤酒吧': 'Craft Beer Bar',
  '屋顶全景酒吧': 'Rooftop Panoramic Bar',
  // 咖啡与轻食
  '特色精品咖啡': 'Specialty Coffee Roasters',
  '海景手冲咖啡馆': 'Oceanview Pour-over Cafe',
  '烘焙与早午餐': 'Bakery & Brunch',
  '花园艺术咖啡馆': 'Garden Art Cafe',
  '露天咖啡吧': 'Open-air Cafe Bar',
  '网红海景咖啡': 'Scenic Seaview Cafe',
  '海滨咖啡小屋': 'Beachside Coffee Shack',
  // 景点地标
  '自然海岸景观': 'Coastal Natural Wonder',
  '历史文化地标': 'Historic Cultural Landmark',
  '国家公园与自然保护区': 'National Park & Nature Reserve',
  '悬崖海蚀奇观': 'Sea Cliff Geological Wonder',
  '文化遗址与神庙': 'Heritage Site & Temple',
  '海滩与冲浪胜地': 'Beach & Surf Haven',
  '城市观景台': 'City Observation Deck',
  '艺术街区与画廊': 'Art District & Galleries',
  '主题公园与影城': 'Theme Park & Studio',
  '大学校园与科技园区': 'University Campus & Tech Park',
  '日落观景海滩': 'Sunset Viewpoint Beach',
  '潜水与浮潜点': 'Diving & Snorkeling Spot',
  // 交通枢纽与工具
  '国际机场': 'International Airport',
  '国内机场': 'Domestic Airport',
  '客运渡轮码头': 'Passenger Ferry Terminal',
  '高速客船码头': 'Speedboat Terminal',
  '租车提还中心': 'Car Rental Center',
  '主要高铁/火车站': 'Central Train Station',
  '城际巴士总站': 'Intercity Bus Terminal',
  '快艇': 'Speedboat',
  '公共轮渡': 'Public Ferry',
  '包车': 'Private Transfer',
  '自驾': 'Self-Drive'
};

// 汇率（v4.2.2 V5-B：只认 run 里登记过来源的数值，不留任何兜底常数）
// 旧实现在这里 `return 7.15`（USD）和 `return 0.125`（PHP），注释写的是「确保英文模式永远
// 不输出半成品未核验免责声明」。后果是：run 根本没有登记汇率时，英文页照样显示一个 $ 数字，
// 而 budget_note 文案承诺的却是「仅在数据集提供已核验汇率时换算」——承诺与实现正好相反。
// 现在拿不到登记因子就返回 null，调用方必须回落到原币种 + 未登记提示；
// 门禁（visual_qa）直接在 DOM 上核对 data-rate-state 与是否还有 $ 金额。
// 状态、因子与文案的唯一来源是 D.budget_fx（references/budget-policy.json + dataset.budget_meta）。
const fxState = () => {
  const box = D.budget_fx;
  if (!box || typeof box !== 'object') return 'STATUS_MISSING';
  return box.rate_status === 'VERIFIED' ? 'VERIFIED'
       : box.rate_status === 'UNREGISTERED' ? 'UNREGISTERED' : 'STATUS_MISSING';
};

const fxFactor = (pair) => {
  if (fxState() !== 'VERIFIED') return null;
  const raw = ((D.budget_fx || {}).factors || {})[pair];
  return (typeof raw === 'number' && isFinite(raw) && raw > 0) ? raw : null;
};

const fxCopy = (key) => {
  const box = (D.budget_fx || {})[key] || {};
  return state.lang === 'cn' ? (box.cn || '') : (box.en || box.cn || '');
};

// 英文态没有登记汇率时，金额按 dataset 里记录的人民币原样显示——原样比编一个好。
const usdAmount = (cnyNumber, pair = 'CNY_USD') => {
  const factor = fxFactor(pair);
  return factor ? '$' + Math.round(cnyNumber * factor).toLocaleString() : null;
};

const isDateTBD = s => !s || /未定|TBD|待定|None|null/i.test(String(s));
const parseDayNum = (val, fallback) => {
  const m = String(val||'').replace(/\D/g, '');
  return m ? parseInt(m, 10) : fallback;
};

// 提取路线预算总金额（兼容纯数字与 v4.1.8 规范字典对象）
const getRouteTotalCny = (budgetVal) => {
  if (budgetVal == null) return 0;
  if (typeof budgetVal === 'object' && budgetVal !== null) {
    return Number(budgetVal.total_cny) || 0;
  }
  const n = Number(budgetVal);
  return isNaN(n) ? 0 : n;
};

/* v4.2.1 SS2.2.1: labels the lexicon could not compose; surfaced for the gate and reader QA. */
const UNTRANSLATED = [];

const CJK_RE_JS = /[\u4e00-\u9fff]/;
// Grammar-only Chinese allowed inside a measurement string: 约 (approx.) and 每 (per).
const METRIC_GRAMMAR_CN = [String.fromCharCode(32422), String.fromCharCode(27599)];

/* Rewrite a string whose Chinese content is *only* measurement grammar (25 min, 14 days...).
   Anything carrying a content word is rejected here and must come from the lexicon or the
   dataset, so this can never invent English for prose. */
function enMetrics(value){
  const text = String(value || '').trim();
  if (!text || !CJK_RE_JS.test(text)) return '';
  const probe = text
    // 第N天 has to be peeled off *before* the unit pass: otherwise '1天' inside '第1天' is
    // stripped first, the bare 第 is left behind and every day label in the budget panel
    // is rejected as untranslatable prose.
    .replace(/第\s*\d+\s*天/g, '')
    .replace(/\d+(?:\.\d+)?\s*(?:分钟|千米|公里|米|小时|晚|天|年|岁)/g, '');
  for (const ch of probe){
    if (CJK_RE_JS.test(ch) && METRIC_GRAMMAR_CN.indexOf(ch) < 0) return '';
  }
  const out = text
    .replace(/第\s*(\d+)\s*天/g, 'Day $1')
    // '14天14晚' is one duration, not two unrelated numbers: expand it before the unit rules
    // split it, or the reader gets '14 days14 nights' with no separator.
    .replace(/(\d+)\s*天\s*(\d+)\s*晚/g, '$1 days $2 nights')
    .replace(/(\d+(?:\.\d+)?)\s*约?\s*分钟/g, '$1 min')
    .replace(/(\d+(?:\.\d+)?)\s*(?:千米|公里)/g, '$1 km')
    .replace(/(\d+(?:\.\d+)?)\s*米/g, '$1 m')
    .replace(/(\d+(?:\.\d+)?)\s*小时/g, '$1 h')
    .replace(/(\d+(?:\.\d+)?)\s*岁/g, '$1')
    .replace(/(\d+(?:\.\d+)?)\s*年/g, '$1 yrs')
    .replace(/(\d+(?:\.\d+)?)\s*晚/g, '$1 nights')
    .replace(/(\d+(?:\.\d+)?)\s*天/g, '$1 days')
    .replace(/\b1 days\b/g, '1 day')
    .replace(/\b1 nights\b/g, '1 night')
    .replace(/约\s*/g, '~')
    .replace(/每/g, 'per ');
  if (CJK_RE_JS.test(out)) return '';   // fail closed: never ship half-converted text
  return out.replace(/\s{2,}/g, ' ').trim();
}

/* SS11.5 bridge: a Chinese string that is a *known entity* resolves to its verified English
   name instead of being dropped, because the evidence already carries it. */
let _cnNameIndex = null;
function enEntityName(value){
  const text = String(value || '').trim();
  if (!text || !CJK_RE_JS.test(text)) return '';
  if (!_cnNameIndex){
    _cnNameIndex = {};
    for (const t of Object.values(D.map_targets || {})){
      if (!t || typeof t !== 'object') continue;
      const en = usableName(t.canonical_name);
      if (!en) continue;
      const key = String(Object.keys(D.map_targets).find(k => D.map_targets[k] === t) || '');
      const tail = key.split('|').pop().trim();
      if (tail) _cnNameIndex[tail] = en;
      if (t.display_name_cn) _cnNameIndex[String(t.display_name_cn).trim()] = en;
    }
    // SS2.2.1: the dataset already ships [中文, English] pairs for destinations, routes and
    // coverage rows. Indexing the pairs (a structural rule) beats re-listing names in a table.
    const pairLists = [D.destinations || [], D.routes || [], D.destination_coverage || []];
    for (const rows of pairLists){
      for (const row of rows){
        const cells = Array.isArray(row) ? row : Object.values(row || {});
        if (cells.length < 2) continue;
        const cn = String(cells[0] || '').trim();
        const en = usableName(cells[1]);
        if (cn && en && CJK_RE_JS.test(cn) && !_cnNameIndex[cn]) _cnNameIndex[cn] = en;
      }
    }
    /* MT-B3（业主 2026-10-31 第 6 条）：专名显示面，两档，都不升级身份。
       tier1 = 同一行里本来就写着的英文名（餐厅名/枢纽名/图题…），列清单住在
                 references/display-name-channel.json::pair_columns，由 scripts/display_names.py
                 在构建期算成 D.name_pairs；撞名条目已在构建期剔出（宁可 pending 也不选一个冒充权威）。
       tier2 = 没有官方英文时的机器翻译显示名 D.machine_translated_display_name，provenance 不完整
                 的条目在构建期就被剔进 display_name_rejected，这里读到的每一条都是明示来源的显示名。
       这两档只喂显示：mapLinks()/地图查询串/evidence/identity_status/VERIFIED 一律不读这里，
       也不许反过来被这里改写。老渔人码头吉罗伊海鲜就是 tier1 的现场证据——
       "Old Fishermans Grotto" 一直在同一行第 3 格，英文页却只能显示 pending。 */
    for (const [cn, en] of Object.entries(D.name_pairs || {})){
      if (cn && usableName(en) && !_cnNameIndex[cn]) _cnNameIndex[cn] = usableName(en);
    }
    for (const [cn, en] of Object.entries(D.machine_translated_display_name || {})){
      if (cn && usableName(en) && !_cnNameIndex[cn]) _cnNameIndex[cn] = usableName(en);
    }
  }
  return _cnNameIndex[text] || '';
}

function loc(value){ return tr(String(value == null ? '' : value), ''); }

/* Meta lines are built by joining several dataset columns with ' · '. Translating the joined
   string can never match a dictionary key, so every part has to be resolved on its own —
   otherwise a fully translated dataset still prints '(translation pending)' for the line. */
function joinLoc(...parts){
  return parts.map(p => loc(p)).filter(s => String(s).trim()).join(' · ');
}

/* SS2.2.1 / SS2.2.3 guard rail: in EN mode no render site may print Chinese, including the
   ones that forgot to call tr(). Deliberate deviation from the contract's "return empty":
   an invisible blank hides the gap from the reader, which is the masking the mandate forbids,
   so untranslated text is labelled and counted instead of deleted. */
const TRANSLATION_PENDING = '(translation pending)';
function visibleText(value){
  const text = String(value == null ? '' : value);
  if (state.lang === 'cn') return text;
  if (!CJK_RE_JS.test(text) || /^https?:\/\//.test(text)) return text;
  const resolved = tr(text, '');
  if (resolved && !CJK_RE_JS.test(resolved)) return resolved;
  return TRANSLATION_PENDING;
}

/* MT-B5 酒店里程碑（业主 2026-11-01 裁决）：**唯一一处**提取规则。
   事实来自原始数据字段（结构化 x[11]/x[12] 优先，其次原始说明 x[10] 的文案），
   与语言无关：两种语言调用同一个 poiMilestone()，得到同一个 {kind, year, source}。
   登记的数字/字段号/文案在 references/data-model.json::hotel_milestone_badges，
   由 test_v422_hotel_milestone_badge.py 做「登记↔实现」双向对账。 */
const MILESTONE_MIN_BADGE_YEAR = 2020;
const MILESTONE_VALID_YEAR_RANGE = [1900, 2100];
const MILESTONE_NOTE_FIELD = 10;
const MILESTONE_STRUCTURED_FIELDS = {opened: 11, renovated: 12};
const MILESTONE_NOTE_PATTERNS = {
  opened: /(202[0-9]).{0,10}?(?:\u5f00\u4e1a|\u5efa|New|Opened)/i,
  renovated: /(202[0-9]).{0,10}?(?:\u7115\u65b0|\u7ffb\u65b0|\u91cd\u88c5|Renovated|Refurbished)/i,
};
const MILESTONE_BADGE_COPY = {
  opened: {cls: 'badge-ok', glyph: '✨', cn: '全新开业', en: ' New'},
  renovated: {cls: 'badge-info', glyph: '🛠️', cn: '全面焕新', en: ' Reno'},
};
function milestoneYear(value){
  if (value === null || value === undefined || value === '') return null;
  const year = parseInt(value, 10);
  if (!Number.isFinite(year) || year < MILESTONE_VALID_YEAR_RANGE[0] || year > MILESTONE_VALID_YEAR_RANGE[1]) {
    return null;   // 非法年份一律不生成徽标（不是当 0 处理，也不是原样印出来）
  }
  return year;
}
function poiMilestone(x, moduleKey){
  const candidates = [];
  for (const kind of ['opened', 'renovated']) {
    const year = milestoneYear(x[MILESTONE_STRUCTURED_FIELDS[kind]]);
    if (year) candidates.push({kind: kind, year: year, source: 'structured_field'});
  }
  if (moduleKey === 'hotels') {           // 只有酒店说明这一列登记过里程碑文案
    const note = String(x[MILESTONE_NOTE_FIELD] == null ? '' : x[MILESTONE_NOTE_FIELD]);
    for (const kind of ['opened', 'renovated']) {
      const m = note.match(MILESTONE_NOTE_PATTERNS[kind]);
      const year = m ? milestoneYear(m[1]) : null;
      if (year) candidates.push({kind: kind, year: year, source: 'dataset_note'});
    }
  }
  const qualified = candidates.filter(c => c.year >= MILESTONE_MIN_BADGE_YEAR);
  if (!qualified.length) return null;
  return qualified.find(c => c.kind === 'opened') || qualified[0];
}

/* ---------- i18n & translations dictionary ---------- */
function tr(cn, en){
  if (state.lang === 'cn') return cn || '';
  if (en && String(en).trim() && !/[\u4e00-\u9fa5]/.test(en)) return String(en).trim();
  if (D.en_text_replacements && D.en_text_replacements[cn] && !/[\u4e00-\u9fa5]/.test(D.en_text_replacements[cn])) {
    return D.en_text_replacements[cn];
  }
  if (typeof cn === 'string') {
    const trimmed = cn.trim();
    // v4.2.1 SS2.2.1: D.category_en is generated by the word-root composer
    // (scripts/category_lexicon.py + references/category-lexicon.json), so coverage does not
    // depend on someone having met this exact label before. CATEGORY_DICT stays as an
    // exception table underneath it.
    if (D.prose_en && D.prose_en[trimmed]) return D.prose_en[trimmed];
    if (D.category_en && D.category_en[trimmed]) return D.category_en[trimmed];
    if (CATEGORY_DICT[trimmed]) return CATEGORY_DICT[trimmed];
    const entityEn = enEntityName(trimmed);
    if (entityEn) return entityEn;
    const metricEn = enMetrics(trimmed);
    if (metricEn) return metricEn;
    if (/[\u4e00-\u9fa5]/.test(trimmed)) {
      // An unmapped Chinese label must not reach the English reader as Chinese, and returning ''
      // is not better: the call sites that test the result for truthiness would then drop the
      // whole slot and the reader sees a blank instead of a gap. The marker is the point:
      //   · this marker plus UNTRANSLATED is exactly what the EN-mode visual QA measures
      //     (scripts/visual_qa.py EN_STATE_JS: dataset.enUntranslated / .enUntranslatedList / CJK census);
      //   · D.category_unmapped is published in the dataset as the *audit* face — the list of labels
      //     the word-root lexicon still cannot decompose.
      // DOC-TRUTH correction (MT-B2, 2026-10-31): this line used to claim "delivery_gate fails on it".
      // No gate reads category_unmapped — measured, not assumed (grep across scripts/*.py hits only
      // category_lexicon.py). Failing loudly is still true, just not there: the PH candidate ships
      // 162 such labels and none of them reach the reader as Chinese, because every one of them is
      // present in D.en_text_replacements (162 of 162, counted from the delivered payload), and tr()
      // consults that map before it ever gets here. If a future round turns category_unmapped into a
      // gate input, it must be registered in the checklist first — this comment is not the place to
      // invent that gate.
      UNTRANSLATED.push(trimmed);
      return TRANSLATION_PENDING;
    }
  }
  return (en && !/[\u4e00-\u9fa5]/.test(en)) ? en : (cn || '');
}

function money(cnyVal){
  if (cnyVal == null) return '';
  if (typeof cnyVal === 'object') {
    if ('total_cny' in cnyVal) {
      cnyVal = cnyVal.total_cny;
    } else {
      console.error('Invalid object passed to money():', cnyVal);
      return '';
    }
  }
  const s = String(cnyVal).trim();
  if (!s || s === '0' || s === '0.0') {
    if (s === '0' || s === '0.0') return (state.lang === 'cn' ? '¥0' : (usdAmount(0) || '¥0'));
    return '';
  }
  if (/免|free/i.test(s)) return state.lang === 'cn' ? '免费' : 'Free';
  const mRange = s.match(/^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$/);
  if (mRange){
    const l = Number(mRange[1]), h = Number(mRange[2]);
    const lo = usdAmount(l), hi = usdAmount(h);
    if (state.lang === 'cn' || !(lo && hi)){
      return '¥' + l.toLocaleString() + '-' + h.toLocaleString();
    }
    return lo + '-' + hi;
  }
  const mPhp = s.match(/^(\d+)\s*(?:比索|php|pesos?)$/i);
  if (mPhp){
    const php = Number(mPhp[1]);
    const phpToCny = fxFactor('PHP_CNY');
    if (!phpToCny) return php.toLocaleString() + ' PHP';
    const cny = Math.round(php * phpToCny);
    if (state.lang === 'cn') return php.toLocaleString() + ' PHP (约¥' + cny.toLocaleString() + ')';
    const usd = usdAmount(cny);
    return php.toLocaleString() + ' PHP (' + (usd ? '≈' + usd : '≈¥' + cny.toLocaleString()) + ')';
  }
  const num = Number(s);
  if (!isNaN(num) && isFinite(num)){
    if (state.lang === 'cn') return '¥' + num.toLocaleString();
    return usdAmount(num) || '¥' + num.toLocaleString();
  }
  // MT-1（业主 2026-10-31）：带币种的金额与区间是 PH transport[*][3] 的真实形状（`约 50-80 元`），
  // 以前落到最后那行 `return s` ⇒ EN 页原样漏中文。只认下面两条**登记过的明确语法**，
  // 输出保持来源币种、不做任何换算（V5-B：budget rate_status = UNREGISTERED，猜汇率就是造事实）。
  // 中文态早退必须放在纯数字分支之后：test_v422_budget_contract 实测过，把它提到前面会让
  // CN 页的 `1000` 丢掉 `¥` 前缀——那是改了读者看到的东西，不在本轮范围内。
  if (state.lang === 'cn') return s;    // 中文态本来就印原文，这两条语法只为英文态服务
  const mCurRange = s.match(/^约?\s*(\d[\d,.]*)\s*[-–~]\s*(\d[\d,.]*)\s*(元|人民币|CNY|¥|￥|美元|USD|\$)$/);
  if (mCurRange){
    const sym = moneySymbol(mCurRange[3]);
    const approx = s.trim().startsWith('约') ? '≈' : '';
    return approx + sym + moneyDigits(mCurRange[1]) + '–' + moneyDigits(mCurRange[2]);
  }
  const mCurOne = s.match(/^约?\s*(\d[\d,.]*)\s*(元|人民币|CNY|¥|￥|美元|USD|\$)(?:\s*\/\s*(晚|人|间|夜|房))?$/);
  if (mCurOne){
    const sym = moneySymbol(mCurOne[2]);
    const approx = s.trim().startsWith('约') ? '≈' : '';
    const unit = mCurOne[3] ? ' / ' + MONEY_UNIT_EN[mCurOne[3]] : '';
    return approx + sym + moneyDigits(mCurOne[1]) + unit;
  }
  // MT-B1 实测补正（mtb_money_distance_probe.py，before 用与封册 sha256 相符的内联渲染器）：
  // transport[n][3] 是**度量槽**——CA 在这里放距离（22公里），PH 在这里放价格（约 50-80 元）。
  // 封存档位里距离靠外层 loc()→enMetrics() 变成 `22 km`；我上一版直接把尾部改成显式 pending，
  // 等于把「不是钱」当成「没登记的钱」，CA 十条距离当场回归。
  // 所以未解析前必须先交给唯一的度量翻译器 enMetrics()（这里只是调用，规则仍只有一处）；
  // 它也不认，才是真缺口：登记原文 + 显式 pending，既不泄漏中文也不编一个数。
  const metric = enMetrics(s);
  if (metric && !CJK_RE_JS.test(metric)) return metric;
  UNTRANSLATED.push(s);
  return TRANSLATION_PENDING;
}

/* money() 的登记语法表（唯一一处）：币种符号与单位都由这里出，渲染点不许自带第三套写法。 */
const MONEY_SYMBOL_CNY = '¥';           // ¥ —— 元/人民币/CNY 一律按本币显示，不换算
const MONEY_SYMBOL_USD = '$';
const MONEY_UNIT_EN = {'晚': 'night', '夜': 'night', '人': 'person', '间': 'room', '房': 'room'};
function moneySymbol(token){
  return (['美元', 'USD', '$'].includes(token)) ? MONEY_SYMBOL_USD : MONEY_SYMBOL_CNY;
}
function moneyDigits(raw){ return String(raw).replace(/,/g, ''); }

/* ---------- app category localization (v4.1.4) ---------- */
const APP_CAT = {
  ride_hailing:['叫车与接送机','Ride-Hailing & Transfers'],
  maps_navigation:['地图与导航','Maps & Navigation'],
  food_discovery:['餐厅发现与评价','Food Discovery & Reviews'],
  food_delivery:['当地外卖','Food Delivery'],
  intercity_booking:['城际票务与渡轮聚合','Intercity & Ferry Booking'],
  urban_transit:['城市轨道与公共交通','Urban Transit'],
  translation:['语言翻译与识图','Translation & OCR'],
  communication:['当地通信与社交','Local Communication'],
  official_tourism:['官方旅游服务','Official Tourism Services'],
  safety_emergency:['旅游警察及紧急服务','Safety & Emergency'],
  activities_booking:['活动与体验预订','Activities & Tours'],
  accommodation_booking:['住宿库存与比价复核','Stay Inventory & Recheck'],
  weather_environment:['天气、空气质量与灾害预警','Weather & Environment'],
  currency_payment:['汇率换算与支付辅助','Currency & Payments']
};
function catLabel(category){
  const m = APP_CAT[category];
  return m ? m[state.lang==='cn'?0:1] : String(category || '');
}

const I18N = {
  scroll_hint:['向下滚动开始','Scroll to begin'],
  days:['天','Days'],
  destinations:['个目的地','destinations'],
  routes_n:['条路线','routes'],
  from_pp:['人均','per person'],
  daily_avg:['日均','per day'],
  pick_route:['选择旅程','Choose your journey'],
  records:['条记录','records'],
  ch:{
    overview:['行程规划','Trip Plan'], stays:['住宿','Stays'], food:['美食','Food'],
    sights:['景点','Sights'], transport:['交通','Transport'], budget:['预算','Budget'],
    toolkit:['在地工具','Toolkit'], notes:['贴士','Notes']
  },
  sub:{
    chart:['路线概览','Route Overview'], itin:['每日行程','Daily Itinerary'], visuals:['沿途影像','Visuals'],
    dests:['目的地概况','Destinations'], coverage:['覆盖范围','Coverage Scope'],
    chains:['当地连锁','Local Chains'], restos:['精选餐厅','Restaurants'], cafes:['特色咖啡','Cafés'],
    exp:['核心体验','Key Experiences'], attr:['必游景点','Attractions'], dive:['潜水胜地','Diving Sites'],
    transfers:['跨城交通','Transfers'], nodes:['枢纽口岸','Stations & Ports'],
    b_overview:['预算总览','Budget Summary'], b_daily:['逐日花费','Daily Breakdown'],
    essential:['核心必备','Essential Apps'], ondemand:['场景工具','Scene Tools'],
    knowledge:['当地要点','Local Essentials'], practical:['入境事务','Entry & Affairs'],
    packing:['行前清单','Packing List'], sources:['研究来源','Research Sources']
  },
  t:{
    duration:['行程时长','Duration'], transport:['交通方式','Transport'], price:['参考预算','Reference budget'],
    corridor:['路线节点','Route nodes'], itinerary:['每日行程','Daily itinerary'],
    route_editorial:['沿途影像','Along the route'],
    destinations_heading:['目的地概况与口岸门户','Destinations & Gateway Ports'],
    coverage_heading:['路线覆盖范围与深度','Route Coverage & Depth'],
    plan_details:['规划详情','Planning details'],
    chain:['当地连锁与便捷选择','Local chains'], restaurants:['餐厅','Restaurants'], cafes:['咖啡馆','Cafés'],
    hotels:['住宿选择','Places to stay'], key_exp:['核心体验','Key experiences'],
    attractions:['景点','Sights'], diving:['潜水','Diving'], transfers:['跨目的地交通','Transfers'],
    nodes:['车站、机场与码头','Stations, airports & ports'], budget_detail:['逐日花费明细','Daily spend breakdown'],
    essential:['出发前建议安装（核心工具）','Essential apps — install before departure'],
    ondemand:['按需安装的场景工具','On-demand & scene tools'], knowledge:['当地旅行要点','Local essentials'],
    practical:['入境与当地事务','Entry & local affairs'], packing:['行前准备清单','Packing checklist'],
    sources:['研究来源','Research sources'],
    items:['项','items'], verified:['已核验','verified'], total:['合计','Total'],
    stay:['住宿','Stay'], food_cat:['餐饮','Food'], transit_cat:['交通','Transit'],
    fun:['活动','Activities'], other:['其他','Other'],
    day:['天','Day'], date:['日期','Date'], plan:['安排','Plan'],
    use_cases:['适用：','Uses: '], limits:['限制：','Limits: '],
    official:['官方直达 ↗','Official Portal ↗'], official_sub:['官网 ↗','Official ↗'],
    appstore:['App Store ↗','App Store ↗'], gplay:['Google Play ↗','Google Play ↗'],
    book_now:['快速预订 / 查班次 ↗','Book / Schedule ↗'],
    sources_total:['来源总数','Total sources'], providers:['来源平台','Providers'],
    detail_only_route1:['逐日明细为主推路线的研究期估算；其余路线可参考上方总价，明细结构一致。',
      'Daily breakdown shown for the primary route; other routes share the same structure, totals shown above.'],
    budget_note:['研究期间估算，含住宿、餐饮、交通、活动与其他，不含国际机票与购物；两人同行人均口径。仅在数据集提供已核验汇率时换算。',
      'Research estimate including stay, food, transit, activities and misc.; excludes international flights and shopping; per person for two travelers. Currency conversion is shown only when the dataset supplies a verified rate.'],
    updated:['数据核验于','Data checked'],
    demo:['本攻略为旅行规划参考，动态信息请临行复核。','Planning reference only; verify dynamic info before travel.']
  },
  day_tag:['Day ','Day '],
  status:{ on_demand:['按需预约','On demand'], verified:['已核验','Verified'], unverified:['未核验','Unverified'] },
  app_status:{ verified_active:['正常运营','Active','badge-ok'], conditional:['条件可用','Conditional','badge-warn'], regional:['特定地区','Regional','badge-info'] },
  tltype:{
    '交通':['交通','Transit','tg-transit'], '酒店':['住宿','Stay','tg-stay'], '住宿':['住宿','Stay','tg-stay'],
    '景点':['景点','Sight','tg-sight'], '餐厅':['餐饮','Food','tg-food'], '美食':['餐饮','Food','tg-food'],
    '咖啡馆':['咖啡','Café','tg-cafe'], '潜水':['潜水','Dive','tg-dive']
  }
};
const t = k => { const v = I18N.t[k]; return Array.isArray(v) ? v[state.lang==='cn'?0:1] : v; };
const pick = (cn,en) => state.lang==='cn' ? (cn||'') : (en||cn||'');

/* ---------- SVG Placeholder & Error Fallback (v4.1.4 Mobile Offline Resilience) ---------- */
function makePlaceholderSvg(title, category){
  const t = String(title || D.country || 'Travel-Scope').slice(0, 24);
  const cat = String(category || 'Scenery');
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 380" width="100%" height="100%">'
    + '<defs>'
    + '<linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">'
    + '<stop offset="0%" stop-color="#123642"/>'
    + '<stop offset="55%" stop-color="#183C55"/>'
    + '<stop offset="100%" stop-color="#2A7080"/>'
    + '</linearGradient>'
    + '</defs>'
    + '<rect width="600" height="380" fill="url(#g)"/>'
    + '<circle cx="510" cy="70" r="130" fill="rgba(200,178,142,0.12)"/>'
    + '<path d="M-40 330 Q 150 210 340 290 T 640 240 L 640 380 L -40 380 Z" fill="rgba(7,20,30,0.45)"/>'
    + '<path d="M40 360 Q 230 270 430 330 T 730 290 L 730 380 L 40 380 Z" fill="rgba(7,20,30,0.35)"/>'
    + '<text x="36" y="295" fill="#E4CEA6" font-family="-apple-system,BlinkMacSystemFont,sans-serif" font-size="12" letter-spacing="3">' + cat.toUpperCase() + '</text>'
    + '<text x="36" y="335" fill="#FFFFFF" font-family="Georgia,serif" font-size="24" font-weight="600">' + t + '</text>'
    + '</svg>';
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
}

/* ---------- DOM helper ---------- */
function h(tag, attrs, ...kids){
  const el = document.createElement(tag);
  if (tag === 'img') el.decoding = 'async';
  if (tag === 'img'){
    // V5-D（V0-L12）：兜底占位图也登记成 fallback——它不是「图片坏了算了」，是读者实际看到的一张生成图。
    el.addEventListener('error', function(){
      if (this.dataset.fallbackFired) return;
      this.dataset.fallbackFired = '1';
      this.dataset.assetDigest = 'fallback';
      this.src = makePlaceholderSvg(this.alt || attrs?.alt || D.country, attrs?.dataset?.category || 'Scenery');
    });
  }
  for (const [k,v] of Object.entries(attrs||{})){
    if (v==null || v===false) continue;
    if (k==='class') el.className=v;
    else if (k==='text') el.textContent=visibleText(v);
    else if (k==='html') el.innerHTML=v;
    else if (k.slice(0,2)==='on' && typeof v==='function') el.addEventListener(k.slice(2), v);
    else if (k==='dataset') Object.assign(el.dataset, v);
    else el.setAttribute(k, v===true?'':v);
  }
  if (tag === 'img' && el.dataset.assetDigest === undefined){
    // 读者页要能被对账成「这张图来自哪一份登记过的字节」。src 既可能是 dataset 里的
    // asset://sha256:…，也可能是渲染期已经解析好的 data URI，所以两种都要能还原出 digest。
    el.dataset.assetDigest = assetDigestOf(el.getAttribute('src')) || 'none';
  }
  for (const kid of kids.flat(Infinity)){
    if (kid==null || kid===false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(visibleText(kid)));
  }
  return el;
}
const linkify = text => {
  const str = String(text||'');
  const out = [], re = /(https?:\/\/[^\s]+)/g; let m, last=0;
  while ((m=re.exec(str))){ if (m.index>last) out.push(str.slice(last,m.index));
    out.push(h('a',{href:m[1],target:'_blank',rel:'noopener noreferrer'},m[1])); last=re.lastIndex; }
  if (last<str.length) out.push(str.slice(last));
  return out;
};
const coordsOK = c => {
  const p = String(c||'').split(',').map(Number);
  return p.length===2 && p.every(Number.isFinite) && Math.abs(p[0])<=90 && Math.abs(p[1])<=180 ? p : null;
};


/* ---------- 地图实体索引缓存 (V4.0.16 根因修复) ---------- */
let _mapTargetsByCoord = null;
let _mapTargetsByName = null;
function getMapTarget(label, coords, dest, enName) {
  const targets = D.map_targets || {};
  if (!_mapTargetsByCoord) {
    _mapTargetsByCoord = {};
    _mapTargetsByName = {};
    for (const [key, t] of Object.entries(targets)) {
      if (t && t.coords) {
        const cRaw = String(t.coords).trim();
        _mapTargetsByCoord[cRaw] = t;
        const p = coordsOK(cRaw);
        if (p) {
          _mapTargetsByCoord[`${p[0].toFixed(5)},${p[1].toFixed(5)}`] = t;
          _mapTargetsByCoord[`${p[0].toFixed(4)},${p[1].toFixed(4)}`] = t;
        }
      }
      if (t && t.canonical_name) {
        _mapTargetsByName[t.canonical_name.trim().toLowerCase()] = t;
      }
      const parts = key.split('|');
      if (parts.length > 1) {
        _mapTargetsByName[parts[1].trim().toLowerCase()] = t;
      }
    }
  }

  // 1. 直接按 key 查找
  if (dest && label && targets[`${dest}|${label}`]) return targets[`${dest}|${label}`];
  if (dest && enName && targets[`${dest}|${enName}`]) return targets[`${dest}|${enName}`];

  // 2. 按经纬度查找
  if (coords) {
    const cStr = String(coords).trim();
    if (_mapTargetsByCoord[cStr]) return _mapTargetsByCoord[cStr];
    const p = coordsOK(coords);
    if (p) {
      const c5 = `${p[0].toFixed(5)},${p[1].toFixed(5)}`;
      if (_mapTargetsByCoord[c5]) return _mapTargetsByCoord[c5];
      const c4 = `${p[0].toFixed(4)},${p[1].toFixed(4)}`;
      if (_mapTargetsByCoord[c4]) return _mapTargetsByCoord[c4];
    }
  }

  // 3. 按店名查找
  if (label && _mapTargetsByName[String(label).trim().toLowerCase()]) {
    return _mapTargetsByName[String(label).trim().toLowerCase()];
  }
  if (enName && _mapTargetsByName[String(enName).trim().toLowerCase()]) {
    return _mapTargetsByName[String(enName).trim().toLowerCase()];
  }

  return null;
}

/* ---------- Google Maps & Apple Maps 精准实体跳转 (V4.1.6 升级) ---------- */
/* v4.2.1 §14.4.3: 名称只允许"可用/不可用"二值判断，禁止再用删字符的方式制造地名。
   v4.2.0 的 151 条 California Venue 就是从 `replace(/[\u4e00-\u9fa5]/g,'')` 出来的。 */
function usableName(value){
  const text = String(value || '').trim();
  if (!text) return '';
  if (/[\u4e00-\u9fa5]/.test(text)) return '';
  if (/^(?:[A-Za-z][A-Za-z .&'-]{0,40}\s)?(?:Venue|Location|Place|Point|Spot|Unnamed|POI|TODO|N\/A)$/i.test(text)) return '';
  if (/^\d{1,4}$/.test(text)) return '';
  return text;
}



function mapLinkAudit(target, provider){
  // §7 的八项属性：DOM ↔ dataset ↔ report 对账的唯一依据，缺一即 V4 门禁 FAIL。
  return {targetId: String((target && target.target_id) || ''),
    entityType: String((target && target.entity_type) || ''),
    criticality: String(target && target.criticality != null ? target.criticality : ''),
    identityStatus: String((target && target.identity_status) || ''),
    coordinateStatus: String((target && target.coordinate_status) || ''),
    linkMode: String((target && target.link_mode) || 'NONE'),
    googleResolutionStatus: String((target && target.google_resolution_status) || ''),
    provider: String(provider)};
}

function mapLinkRecord(target, provider){
  if(!target) return null;
  const byProvider = target.map_link_by_provider || {};
  const primary = (D.map_link_ui && D.map_link_ui.primary_provider) || 'google';
  if(provider === primary){
    // 容器优先；没有容器的旧数据集退回单值字段。两者都是选择器写的值——
    // 本函数从不构造 URL、从不判断主机名、从不猜名称（§4 禁止动作 + §9）。
    return byProvider[provider] || {link_mode: target.link_mode,
      map_link_url: target.map_link_url, link_notices: target.link_notices,
      link_selection_reason: target.link_selection_reason};
  }
  return byProvider[provider] || null;
}

/* v4.2.2 §7：地图入口只消费 references/map-link-selection.json 选好的结果。
   四种状态各有确定形态：实体直达 / 具名搜索（落点未核验）/ 坐标地标 / 无按钮。
   旧实现里的 Place ID 参数拼接、纯坐标兜底、只带国家的搜索串、渲染层自建 Apple 链接全部删除。 */
function mapLinks(label, coords, dest, enName){
  const target = getMapTarget(label, coords, dest, enName);
  const ui = D.map_link_ui || {};
  const providers = (ui.rendered_providers && ui.rendered_providers.length)
    ? ui.rendered_providers : ['google'];
  const copy = ui.button_copy || {};
  const noticeText = ui.notices || {};
  const kids = [];
  providers.forEach(provider => {
    const record = mapLinkRecord(target, provider);
    const mode = String((record && record.link_mode) || 'NONE');
    const href = String((record && record.map_link_url) || '');
    if(mode === 'NONE' || !href) return;
    const spec = copy[mode] || {};
    const text = state.lang === 'cn' ? (spec.cn || '') : (spec.en || '');
    if(!text) return;                       // 文案未登记 ⇒ 不给按钮（配置缺失即阻断）
    kids.push(h('a',{href: href, target:'_blank', rel:'noopener noreferrer',
      dataset: mapLinkAudit(target, provider)}, text));
    ((record.link_notices) || []).forEach(key => {
      const notice = noticeText[key];
      if(notice) kids.push(h('small',{class:'map-unlocated'},
        state.lang === 'cn' ? notice.cn : notice.en));
    });
  });
  if(!kids.length){
    const none = copy.NONE || {};
    return h('div',{class:'map-links map-links-none',dataset: mapLinkAudit(target, providers[0])},
      h('small',{class:'map-unavailable'}, state.lang === 'cn'
        ? (none.cn_note || '地图入口不可用') : (none.en_note || 'Map entry unavailable')));
  }
  return h('div',{class:'map-links'}, ...kids);
}

/* ---------- 跨目的地交通第三方/官方预订平台链接生成 (V4.1.6 彻底去硬编码) ---------- */
function getTransportLinks(operator, routeDesc, timetable, booking){
  const links = [];
  if (timetable && typeof timetable === 'string' && timetable.startsWith('http')) {
    links.push({label: pick('官方时刻表 ↗','Timetable ↗'), url: timetable});
  }
  if (booking && typeof booking === 'string' && booking.startsWith('http')) {
    links.push({label: pick('官方预订 ↗','Official Booking ↗'), url: booking});
  }
  if (links.length) return links;

  // 从当前国家数据集的 local_apps 中动态匹配交通应用
  const localApps = D.local_apps || [];
  const transitApp = localApps.find(a => ['intercity_booking','ride_hailing','urban_transit'].includes(a.category) && a.availability_status!=='retired');
  if (transitApp){
    const appUrl = transitApp.official_url || transitApp.ios_url || transitApp.android_url;
    const appName = state.lang==='cn' ? transitApp.name : (transitApp.name_en || transitApp.name);
    if (appUrl) {
      links.push({label: pick(`通过 ${appName} 查询 ↗`, `Via ${appName} ↗`), url: appUrl});
    }
  }

  // 兜底搜索词：使用当前国家名称，严禁硬编码其他国家
  if (!links.length){
    const country = D.country_en || D.country || '';
    links.push({label: t('book_now'), url:`https://www.google.com/search?q=${encodeURIComponent((operator || routeDesc) + ' ' + country + ' booking tickets')}`});
  }
  return links;
}

/* ---------- section media lookup ---------- */
function sectionMediaItem(place, moduleKey){
  const list = D.section_media.filter(m => m.destination===place && m.modules.includes(moduleKey));
  if (!list.length) return null;
  return list.find(m=>m.primary_module===moduleKey) || list[0];
}
function sectionImage(place, moduleKey){
  const item = sectionMediaItem(place, moduleKey);
  return item ? assetUrl(item.image) : null;
}
/* R3B（业主 2026-11-03 裁「采用现有 designed_no_photo_state，不再发明第二套无图机制」）：
   「这个槽位正式没有图」是数据层的事实，不是渲染期的意外。渲染层只认 dataset 那一行的身份，
   不自己另判「图片没加载上就算无图」——那样读者看到的就是偶然少一张图。
   判据词表归 references/media-policy.json::designed_no_photo_state（Python 侧 local_media_gate
   ::is_no_photo_row 是同一份登记的另一半；JS 拿不到 references/，所以这里只比登记值字面量，
   两边由 test_v422_no_photo_state.py::RendererContractTests 与登记面双向核对，漂了即红）。 */
function sectionMediaState(item){
  if (!item) return null;
  const level = String(item.selection_level || ''), role = String(item.asset_role || '');
  if (level === 'designed_no_photo_state' || role === 'designed_no_photo_state') return 'designed_no_photo_state';
  return 'photographic';
}

/* ---------- common ---------- */
function currentRoute(){ return D.routes.find(r=>r[0]===state.route) || D.routes[0]; }
function routeHeroItem(r){
  return D.editorial_media.find(e=>e.route===r[0]) || null;
}
function routeHero(r){
  const em = routeHeroItem(r);
  return assetUrl(em ? em.image : D.hero_image);
}
function routeHeroTiers(r){
  const em = routeHeroItem(r);
  return (em && em.image_srcset) || D.hero_srcset || [];
}
function panelHead(id, count){
  const v = I18N.ch[id];
  return h('div',{class:'panel-head'},
    h('h2',{}, v[state.lang==='cn'?0:1]),
    h('span',{class:'ph-en'}, v[1]),
    h('span',{class:'ph-count'}, count!=null ? count+' '+t('items') : ''));
}

/* ---------- cover ---------- */
function renderCover(){
  const r = currentRoute();
  const bg = document.getElementById('cover-bg');
  bg.onerror = function(){
    if (this.dataset.fallbackFired) return;
    this.dataset.fallbackFired = '1';
    this.dataset.assetDigest = 'fallback';
    this.src = makePlaceholderSvg(pick(D.country, D.country_en), 'Editorial Cover');
  };
  bg.src = routeHero(r);
  bg.dataset.assetDigest = assetDigestOf(bg.src) || 'none';
  applyTiers(bg, routeHeroTiers(r), '100vw');
  bg.setAttribute('aria-hidden', 'true');
  bg.decoding = 'async';
  bg.classList.remove('is-live'); requestAnimationFrame(()=>bg.classList.add('is-live'));
  const langBtnLabel = document.getElementById('lang-btn');
  if (langBtnLabel) langBtnLabel.textContent = pick('English','中文');
  document.getElementById('scroll-hint').textContent = I18N.scroll_hint[state.lang==='cn'?0:1];

  const title = document.getElementById('cover-title');
  title.innerHTML='';
  title.append(h('small',{}, pick('Travel-Scope 旅行攻略','Travel-Scope Guide')), pick(D.country, D.country_en));

  const dur = String(r[3]||''), daysMatch = dur.match(/\d+/);
  // CN glues the unit ('14天'); English needs a space ('14 Days'). The stat label below the big
  // number is a bare noun and must not get the same join, so the separator is language-specific here.
  document.getElementById('cover-sub').textContent =
    (daysMatch ? daysMatch[0] + (state.lang === 'cn' ? I18N.days[0] : ' ' + I18N.days[1]) + ' · ' : '')
    + tr(r[0], r[1]);
  document.getElementById('cover-lead').textContent = tr(r[6], r[7]);

  const stats = document.getElementById('cover-stats');
  stats.innerHTML='';
  const total = getRouteTotalCny(D.route_budgets?.[r[0]]);
  const statDefs = [
    [daysMatch?daysMatch[0]:(D.duration_days||'–'), I18N.days[state.lang==='cn'?0:1]],
    [D.destinations.length, I18N.destinations[state.lang==='cn'?0:1]],
    [D.routes.length, I18N.routes_n[state.lang==='cn'?0:1]],
    [total ? money(total) : '–', I18N.from_pp[state.lang==='cn'?0:1]]
  ];
  statDefs.forEach(([v,l])=>stats.append(h('div',{class:'stat'},h('b',{},String(v)),h('span',{},l))));

  const rp = document.getElementById('route-pick');
  rp.innerHTML='';
  D.routes.forEach(rc=>{
    const rcTotal = getRouteTotalCny(D.route_budgets?.[rc[0]]);
    rp.append(h('button',{class:'route-card',type:'button','aria-pressed':rc[0]===state.route,
      dataset:{route:rc[0]},
      onclick:()=>chooseRoute(rc[0])},
      h('small',{}, I18N.pick_route[state.lang==='cn'?0:1]),
      h('b',{}, tr(rc[0], rc[1])),
      h('em',{}, joinLoc(rc[3])+' · '+money(rcTotal)+'/'+pick('人','pax'))));
  });
}

/* ---------- nautical chart background SVG ---------- */
const CHART_SVG =
'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1360 360" preserveAspectRatio="xMidYMid slice">'
+'<rect width="1360" height="360" fill="none"/>'
+'<g stroke="#b2a684" stroke-width="1" opacity="0.55">'
+'<line x1="0" y1="70" x2="1360" y2="70"/><line x1="0" y1="180" x2="1360" y2="180"/><line x1="0" y1="290" x2="1360" y2="290"/>'
+'<line x1="200" y1="0" x2="200" y2="360" stroke-dasharray="5 7"/>'
+'<line x1="520" y1="0" x2="520" y2="360" stroke-dasharray="5 7"/>'
+'<line x1="840" y1="0" x2="840" y2="360" stroke-dasharray="5 7"/>'
+'<line x1="1160" y1="0" x2="1160" y2="360" stroke-dasharray="5 7"/>'
+'</g>'
+'<g fill="none" stroke="#8fa98c" stroke-width="1.3" opacity="0.7">'
+'<path d="M-20 250 C 180 200, 340 300, 560 238 S 940 170, 1180 232 S 1320 250 1380 214"/>'
+'<path d="M-20 120 C 200 70, 420 150, 640 104 S 1000 60, 1220 116 S 1340 130 1380 96"/>'
+'</g>'
+'<g transform="translate(1255,78)" opacity="0.85">'
+'<circle r="40" fill="none" stroke="#6f7d83" stroke-width="1.2"/>'
+'<circle r="28" fill="none" stroke="#6f7d83" stroke-width="1"/>'
+'<path d="M0 -38 L7 0 L0 38 L-7 0 Z" fill="#33566a"/>'
+'<path d="M-38 0 L0 -7 L38 0 L0 7 Z" fill="#6f8593"/>'
+'<text y="-46" text-anchor="middle" font-size="13" fill="#33566a" font-family="Georgia,serif">N</text>'
+'</g>'
+'</svg>';

/* ---------- overview: nautical chart route card ---------- */
function routeChart(r){
  const nodes = String(r[2]||'').split(/→|->|\s+-\s+|—/).map(s=>s.trim()).filter(Boolean);
  const line = h('div',{class:'route-line'});
  nodes.forEach((n,i)=>line.append(h('div',{class:'rl-node'},
    h('span',{class:'mk'}), tr(n, D.en_text_replacements?.[n]))));
  const meta = h('dl',{class:'meta'},
    h('div',{},h('dt',{},t('duration')),h('dd',{},loc(r[3]))),
    h('div',{},h('dt',{},t('transport')),h('dd',{},tr(r[4], D.en_text_replacements?.[r[4]]))),
    h('div',{},h('dt',{},t('price')),h('dd',{},money(getRouteTotalCny(D.route_budgets?.[r[0]])))));
  return h('div',{class:'chart reveal', id:'sub-route-chart'},
    h('div',{class:'chart-bg',html:CHART_SVG}),
    h('div',{class:'ct'},
      h('div',{class:'kicker'}, pick('推荐旅程 / 可切换','Your journey / switchable')),
      h('div',{class:'rt-name'}, tr(r[0],r[1])),
      h('p',{class:'rt-desc'}, tr(r[6], r[7])),
      line, meta),
    h('div',{class:'scale'}, pick('海里 · 示意','nautical miles')));
}

/* ---------- itinerary timeline (修复 Day 1 ~ Day 12 全量显示) ---------- */
function itineraryBlock(r){
  const rows = D.itinerary.filter(x=>x[0]===r[0]);
  const byDay = new Map();

  // 构建目的地映射表，用于提取行程每日所在城市
  const destEnMap = new Map();
  (D.destinations || []).forEach(d => { if (d[0]) destEnMap.set(d[0], d[1] || d[0]); });
  const poiToDest = new Map();
  ['hotels', 'restaurants', 'cafes', 'attractions', 'dive_sites', 'transport_nodes'].forEach(k => {
    (D[k] || []).forEach(row => {
      if (row[0] && row[1]) poiToDest.set(row[1], row[0]);
      if (row[0] && row[2]) poiToDest.set(row[2], row[0]);
    });
  });
  if (D.map_targets) {
    Object.entries(D.map_targets).forEach(([k, v]) => {
      if (v && v.destination) {
        poiToDest.set(k, v.destination);
        if (v.canonical_name) poiToDest.set(v.canonical_name, v.destination);
      }
    });
  }

  // 按天数分组
  rows.forEach(x=>{
    const m = String(x[1]||'').match(/\d+/);
    const dayNum = m ? Number(m[0]) : (Number(x[2])||1);
    if (!byDay.has(dayNum)) byDay.set(dayNum, []);
    byDay.get(dayNum).push(x);
  });

  const sortedDays = [...byDay.entries()].sort((a,b)=>a[0]-b[0]);
  const dates = new Map(D.budget.map((b, idx)=>[parseDayNum(b[0], idx+1), b[1]]));
  const wrap = h('div',{class:'block reveal', id:'sub-itinerary'});
  wrap.append(h('div',{class:'module-head'},h('h3',{class:'serif'},t('itinerary')),
    h('span',{},rows.length+' '+t('items'))));

  sortedDays.forEach(([d,items],i)=>{
    const det = h('details',{class:'day', open:i===0});
    const dNum = parseDayNum(d, i+1);
    const date = dates.get(dNum);
    const isTbd = isDateTBD(date);

    // 提取当日城市集合
    const dayCities = [];
    items.forEach(it=>{
      const dest = poiToDest.get(it[4]) || (it[6] && String(it[6])) || '';
      if (dest && !dayCities.includes(dest)) dayCities.push(dest);
    });

    // 提取当日预算/路线计划主题
    const dBudget = D.budget.find((b, idx) => parseDayNum(b[0], idx+1) === dNum) || D.budget[dNum-1];
    const rawPlan = dBudget ? (dBudget[2] || '').trim() : '';

    if (!dayCities.length && rawPlan) {
      (D.destinations || []).forEach(d => {
        if (d[0] && rawPlan.includes(d[0]) && !dayCities.includes(d[0])) dayCities.push(d[0]);
      });
    }

    // v4.2.1 SS4.2.3 + SS2.2.1: the city slot may only carry real destinations. Distance
    // columns (518) and day labels (第1天) were landing here and printing into EN headers.
    const knownDest = new Set((D.destinations || []).map(d => String(d[0] || '').trim()));
    const cleanDayCities = dayCities.filter(c => {
      const value = String(c || '').trim();
      if (!value) return false;
      if (/^\d+(\.\d+)?$/.test(value)) return false;
      return knownDest.has(value) || destEnMap.has(value);
    });
    dayCities.length = 0;
    cleanDayCities.forEach(c => dayCities.push(c));
    const dayCitiesEn = dayCities.map(c => destEnMap.get(c) || c);
    const dayCitiesStr = state.lang === 'cn' ? dayCities.join(' / ') : dayCitiesEn.join(' / ');

    let planStr = rawPlan;
    if (state.lang !== 'cn') {
      // tr() first: the day theme is dataset prose (prose_en). The two structural rewrites stay
      // underneath it, and are checked against the pending marker because tr() now answers a gap
      // with a marker instead of an empty string.
      let planEn = tr(rawPlan, '');
      if (planEn === TRANSLATION_PENDING) {
        if (/走廊巡礼\s*Day\s*(\d+)/i.test(rawPlan)) planEn = rawPlan.replace(/走廊巡礼\s*Day\s*(\d+)/i, 'Corridor Tour Day $1');
        else if (/第\s*(\d+)\s*天/i.test(rawPlan)) planEn = rawPlan.replace(/第\s*(\d+)\s*天/i, 'Day $1');
        else planEn = D.en_text_replacements?.[rawPlan] || '';
      }
      // MT-1 REVISE（业主 2026-10-31）：EN 模式不许回落中文。tr() 已经在返回 marker 时
      // 把原始 rawPlan 登记进 UNTRANSLATED（见 line 313），所以缺译在这里既显式可见、又仍然有账。
      planStr = planEn || TRANSLATION_PENDING;
    }

    // 结构化 Header：展示天数、城市、核心主题，彻底告别读者迷茫
    const sumChildren = [
      h('span',{class:'d-no'}, I18N.day_tag[state.lang==='cn'?0:1]+dNum)
    ];
    if (dayCitiesStr) {
      sumChildren.push(h('span',{class:'d-dest'}, '· ' + dayCitiesStr));
    }
    if (planStr && !planStr.startsWith('Day ') && !planStr.startsWith('Corridor Tour')) {
      sumChildren.push(h('span',{class:'d-theme'}, '| ' + planStr));
    }
    // A "第1天" string in the date slot is not a date; printing it duplicates the day number
    // and leaks Chinese into the English page.
    const looksLikeDayLabel = /^第\s*\d+\s*天$/.test(String(date || '').trim());
    if (!isTbd && date && !looksLikeDayLabel) {
      sumChildren.push(h('span',{class:'d-date'}, date));
    }
    sumChildren.push(h('span',{class:'d-count'}, items.length+' '+t('items')));
    sumChildren.push(h('span',{class:'d-toggle'},'+'));

    det.append(h('summary',{}, ...sumChildren));

    const body = h('div',{class:'day-body'});
    items.forEach(it=>{
      const meta = I18N.tltype[it[3]] || ['','','tg-transit'];
      const rawText = it[4]||'';
      const transText = tr(rawText, D.en_text_replacements?.[rawText]);
      const itemDest = dayCities[0] || null;
      body.append(h('div',{class:'tl-item'},
        h('span',{class:'tl-tag '+meta[2]}, meta[state.lang==='cn'?0:1]),
        h('div',{class:'tl-text'}, linkify(transText),
          coordsOK(it[5]) ? mapLinks(rawText, it[5], itemDest, transText !== rawText ? transText : null) : null)));
    });
    det.append(body); wrap.append(det);
  });
  return wrap;
}

function editorialBlock(r){
  const items = D.editorial_media.filter(e=>e.route===r[0]);
  if (!items.length) return null;
  const wrap = h('div',{class:'block reveal', id:'sub-editorial'});
  wrap.append(h('div',{class:'module-head'},h('h3',{class:'serif'},t('route_editorial')),
    h('span',{},items.length+' '+t('items'))));
  const grid = h('div',{class:'editorial'});
  items.forEach(e=>{
    const cap = h('figcaption',{},
      h('span',{class:'ed-kicker'}, tr(e.destination, D.en_text_replacements?.[e.destination])),
      h('h4',{}, tr(e.title, e.title_en)),
      h('small',{}, pick('摄影 ','Photo ')+String(e.author||'').replace(/^a href="[^"]*">([^<]*)<\/a>/,'$1')+' · '+e.license+
        (e.commons_page?' · ':''),
        e.commons_page ? h('a',{href:e.commons_page,target:'_blank',rel:'noopener noreferrer'},'来源 Source ↗') : null));
    grid.append(h('figure',{class:'ed-figure'},
      h('div',{class:'ed-img'},applyTiers(h('img',{src:assetUrl(e.image),alt:tr(e.title,e.title_en),loading:'lazy'}), e.image_srcset, '(max-width:900px) 100vw, 45vw')), cap));
  });
  wrap.append(grid); return wrap;
}

function destinationsBlock(){
  const rows = D.destinations || [];
  if (!rows.length) return null;
  const block = h('div',{class:'block reveal', id:'sub-destinations'});
  block.append(h('div',{class:'module-head'},
    h('h3',{class:'serif'}, t('destinations_heading')),
    h('span',{}, rows.length+' '+t('items'))));
  const grid = h('div',{class:'dest-grid'});
  rows.forEach(d=>{
    // Canonical destination tuple (gen_travel_scope.format_destination_for_table):
    // [cn, en, region, experience, days, season, arrival, in_route]. The old reads pointed at
    // d[9]/d[10] (never present) and printed 最佳季节 under "口岸枢纽" and 到达方式 under
    // "时区货币" — two facts shown under the wrong label, in both languages.
    const dName = tr(d[0], d[1]);
    const dRegion = loc(d[2]);
    const dExperience = loc(d[3]);
    const dDays = loc(d[4]);
    const dSeason = loc(d[5]);
    const dArrival = joinLoc(d[6], d[7]);
    const dCard = h('article',{class:'dest-card'},
      h('div',{class:'dest-card-head'},
        h('h4',{}, dName),
        dDays ? h('span',{class:'dest-iata'}, dDays) : null),
      dRegion ? h('div',{class:'dest-tagline'}, dRegion) : null,
      h('div',{class:'dest-meta'},
        h('div',{}, h('small',{}, pick('到达方式','Arrival')), h('b',{}, dArrival || '–')),
        h('div',{}, h('small',{}, pick('最佳季节','Best season')), h('b',{}, dSeason || '–'))),
      dExperience ? h('div',{class:'dest-desc'}, '✦ ', dExperience) : null,
      mapLinks(d[0], d[3], d[0], d[1]));
    grid.append(dCard);
  });
  block.append(grid);
  return block;
}

function coverageBlock(){
  const rows = D.destination_coverage || [];
  if (!rows.length) return null;
  const block = h('div',{class:'block reveal', id:'sub-coverage'});
  block.append(h('div',{class:'module-head'},
    h('h3',{class:'serif'}, t('coverage_heading')),
    h('span',{}, rows.length+' '+t('items'))));
  const wrap = h('div',{class:'coverage-table-wrap'});
  const table = h('table',{class:'coverage-table'});
  table.append(h('thead',{}, h('tr',{},
    h('th',{}, pick('目的地','Destination')),
    h('th',{}, pick('住宿','Stays')),
    h('th',{}, pick('餐饮','Food')),
    h('th',{}, pick('咖啡','Café')),
    h('th',{}, pick('景点','Sights')),
    h('th',{}, pick('潜水','Diving')),
    h('th',{}, pick('核心覆盖范围','Coverage Scope')))));
  const tbody = h('tbody',{});
  rows.forEach(r=>{
    tbody.append(h('tr',{},
      h('td',{}, h('b',{}, tr(r[0], r[1]))),
      h('td',{}, String(r[2]||0)),
      h('td',{}, String(r[3]||0)),
      h('td',{}, String(r[4]||0)),
      h('td',{}, String(r[5]||0)),
      h('td',{}, String(r[6]||0)),
      h('td',{}, tr(r[7]||'', D.en_text_replacements?.[r[7]]))));
  });
  table.append(tbody);
  wrap.append(table);
  block.append(wrap);
  return block;
}

function overviewPanel(){
  const r = currentRoute();
  const p = h('section',{class:'panel',id:'panel-overview',role:'tabpanel','aria-labelledby':'tab-overview'});
  const w = h('div',{class:'wrap'});
  w.append(panelHead('overview', D.itinerary.filter(x=>x[0]===r[0]).length));

  // Subnav
  const subnav = h('div',{class:'subnav'},
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('sub-route-chart')}, I18N.sub.chart[state.lang==='cn'?0:1]),
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('sub-itinerary')}, I18N.sub.itin[state.lang==='cn'?0:1]),
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('sub-editorial')}, I18N.sub.visuals[state.lang==='cn'?0:1]),
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('sub-destinations')}, I18N.sub.dests[state.lang==='cn'?0:1]),
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('sub-coverage')}, I18N.sub.coverage[state.lang==='cn'?0:1])
  );
  w.append(subnav);

  w.append(routeChart(r));
  w.append(h('div',{style:'height:clamp(20px,3vh,32px)'}));
  w.append(itineraryBlock(r));
  const ed = editorialBlock(r); if (ed) w.append(ed);
  const destBlock = destinationsBlock(); if (destBlock) w.append(destBlock);
  const covBlock = coverageBlock(); if (covBlock) w.append(covBlock);
  p.append(w); return p;
}

/* ---------- grouped POI block ---------- */
function poiGroupBlock(moduleKey, anchorPrefix){
  const rows = D[moduleKey] || [];
  const groups = new Map();
  rows.forEach(x=>{ if(!groups.has(x[0])) groups.set(x[0],[]); groups.get(x[0]).push(x); });
  const block = h('div',{class:'block reveal', id: anchorPrefix ? anchorPrefix : ('mod-'+moduleKey)});
  block.append(h('div',{class:'module-head'},h('h3',{class:'serif'},t(moduleKey)),
    h('span',{},rows.length+' '+t('items'))));
  let bi = 0;
  [...groups].forEach(([place,items])=>{
    const sectionItem = sectionMediaItem(place, moduleKey);
    const noPhoto = sectionMediaState(sectionItem) === 'designed_no_photo_state';
    const img = noPhoto ? null : sectionImage(place, moduleKey);
    const enName = (D.destinations.find(d=>d[0]===place)||[,''])[1]||place;
    const destName = tr(place, enName);
    const det = h('details',{class:'branch', id:`branch-${moduleKey}-${bi}`, open:bi===0});
    det.append(h('summary',{},
      h('span', Object.assign({class:'branch-visual'+(noPhoto?' no-photo':'')},
                              noPhoto?{dataset:{mediaState:'designed_no_photo_state'}}:{}),
        noPhoto ? h('span',{class:'no-photo-label'}, pick('暂无已核验图片','No verified photograph'))
                : (img ? applyTiers(h('img',{src:img,alt:destName,loading:'lazy'}),
                         sectionItem && sectionItem.image_srcset, '(max-width:768px) 100vw, 50vw') : null),
        (!noPhoto && img && (() => {
          const sm = (D.section_media || []).find(m => m.destination === place && m.modules && m.modules.includes(moduleKey));
          return sm && (sm.asset_role === 'destination_atmosphere' || String(sm.selection_level || '').includes('reference'));
        })()) ? h('span',{class:'badge-atmosphere'}, pick('目的地氛围参考','Atmosphere Reference')) : null,
        h('span',{}, destName)),
      h('span',{class:'branch-copy'},
        h('b',{}, destName),
        h('em',{}, items.length+' '+t('items'))),
      h('span',{class:'branch-toggle'},'+')));
    const rec = h('div',{class:'branch-records'});
    const coordCol = (moduleKey==='attractions'||moduleKey==='dive_sites') ? 6 : 7;
    items.forEach(x=>{
      const poiName = tr(x[1], x[2]);
      const poiCategory = tr(x[3], D.en_text_replacements?.[x[3]]);
      const poiNote = tr(x[10], D.en_text_replacements?.[x[10]]);

      // MT-B5（业主 2026-11-01 裁决，seal-41 第 1 条）：徽标说的是**数据**，不是译文的一部分。
      // 上一版从 poiNote（tr() 之后的文本）正则找年份，于是「说明还没译成英文」会连带把
      // ✨/🛠️ 徽标一起吞掉：PH 成品实测 7 个徽标在英文态整块消失（既不是泄漏也不是 pending，
      // 是第三种隐身）。现在解析源固定为原始 x[10]，结构化 x[11]/x[12] 有值时优先，原始说明只当
      // dataset_note 来源（不升级为 VERIFIED 或独立核验证据）；CN/EN 拿到的是同一个
      // {kind, year, source}，只有文案各自本地化。规则登记：data-model.json::hotel_milestone_badges
      const milestone = poiMilestone(x, moduleKey);
      const isNew = Boolean(milestone);
      let badgeTag = null;
      if (moduleKey === 'hotels' && milestone) {
        const copy = MILESTONE_BADGE_COPY[milestone.kind];
        badgeTag = h('span', {class: 'badge ' + copy.cls, style: 'margin-left:6px; font-weight:600;'},
          `${copy.glyph} ${milestone.year}${pick(copy.cn, copy.en)}`);
      }

      rec.append(h('article',{class:'poi', dataset:{isNew: isNew ? '1' : '0',
        milestone: milestone ? milestone.kind + ':' + milestone.year + ':' + milestone.source : ''}},
        h('h4',{}, poiName),
        h('div',{class:'poi-sub'}, poiCategory,
          x[4] ? h('span',{}, ' · ', money(x[4])) : null,
          badgeTag),
        poiNote ? h('p',{}, poiNote) : null,
        mapLinks(x[1], x[coordCol], place, x[2])));
    });
    det.append(rec); block.append(det); bi++;
  });
  return block;
}

function setHotelFilter(type, btn){
  document.querySelectorAll('.hotel-filter-bar .subnav-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('#panel-stays .poi').forEach(card => {
    if (type === 'all') {
      card.style.display = '';
    } else if (type === 'new') {
      card.style.display = card.dataset.isNew === '1' ? '' : 'none';
    }
  });
}

function staysPanel(){
  const p = h('section',{class:'panel',id:'panel-stays',role:'tabpanel','aria-labelledby':'tab-stays',hidden:true});
  const w = h('div',{class:'wrap'});
  w.append(panelHead('stays', D.hotels.length));

  // Destination Subnav
  const dests = [...new Set(D.hotels.map(x=>x[0]))];
  const subnav = h('div',{class:'subnav'});
  dests.forEach((dst,idx)=>{
    const en = (D.destinations.find(d=>d[0]===dst)||[,''])[1]||dst;
    subnav.append(h('button',{class:'subnav-btn',onclick:()=>{
      const target = document.getElementById(`branch-hotels-${idx}`);
      if (target){ target.open = true; target.scrollIntoView({behavior:'smooth'}); }
    }}, tr(dst,en)));
  });
  w.append(subnav);

  // Hotel Quick Filter Bar (V4.1.9)
  const filterBar = h('div',{class:'subnav hotel-filter-bar', style:'margin-bottom:12px;'},
    h('button',{class:'subnav-btn active',onclick:(e)=>setHotelFilter('all', e.target)}, pick('全部住宿','All Stays')),
    h('button',{class:'subnav-btn',onclick:(e)=>setHotelFilter('new', e.target)}, pick('✨ 2020+次新/焕新','✨ 2020+ New/Renovated'))
  );
  w.append(filterBar);

  w.append(poiGroupBlock('hotels', 'stays-hotels'));
  p.append(w); return p;
}

/* ---------- food: deep chains + groups ---------- */
function chainsBlock(){
  const rows = D.local_chains;
  const block = h('div',{class:'block deep reveal', id:'food-chains'});
  block.append(h('div',{class:'module-head'},h('h3',{class:'serif'},t('chain')),
    h('span',{},rows.length+' '+t('items'))));
  const grid = h('div',{class:'num-grid'});
  rows.forEach((x,i)=>{
    const chainName = tr(x[1], x[2]);
    const chainType = tr(x[3], D.en_text_replacements?.[x[3]]);
    const chainDesc = tr(x[4], D.en_text_replacements?.[x[4]]);
    const chainMeta = joinLoc(x[5], x[6], x[7]);
    grid.append(h('div',{class:'num-card'},
      h('span',{class:'n'},String(i+1).padStart(2,'0')),
      h('small',{}, chainType),
      h('h4',{}, chainName),
      h('p',{}, chainDesc),
      h('span',{class:'nc-meta'}, chainMeta)));
  });
  block.append(grid); return block;
}

function foodPanel(){
  const p = h('section',{class:'panel',id:'panel-food',role:'tabpanel','aria-labelledby':'tab-food',hidden:true});
  const w = h('div',{class:'wrap'});
  w.append(panelHead('food', D.restaurants.length+D.cafes.length));

  // Subnav
  const subnav = h('div',{class:'subnav'},
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('food-chains')}, I18N.sub.chains[state.lang==='cn'?0:1]),
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('food-restaurants')}, I18N.sub.restos[state.lang==='cn'?0:1]),
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('food-cafes')}, I18N.sub.cafes[state.lang==='cn'?0:1])
  );
  w.append(subnav);

  w.append(chainsBlock());
  w.append(poiGroupBlock('restaurants', 'food-restaurants'));
  w.append(poiGroupBlock('cafes', 'food-cafes'));
  p.append(w); return p;
}

/* ---------- sights: deep numbered key experiences + groups ---------- */
function keyExpBlock(){
  const rows = D.worth_it;
  const block = h('div',{class:'block deep reveal', id:'sights-worth-it'});
  block.append(h('div',{class:'module-head'},h('h3',{class:'serif'},t('key_exp')),
    h('span',{},rows.length+' '+t('items'))));
  const grid = h('div',{class:'num-grid'});
  rows.forEach((x,i)=>{
    const tag = tr(x[0], D.en_text_replacements?.[x[0]]);
    const name = tr(x[1], x[2]);
    const desc = tr(x[3], D.en_text_replacements?.[x[3]]);
    const meta = joinLoc(x[4], x[5], x[6], x[7]);
    grid.append(h('div',{class:'num-card'},
      h('span',{class:'n'},String(i+1).padStart(2,'0')),
      h('small',{}, tag),
      h('h4',{}, name),
      h('p',{}, desc),
      h('span',{class:'nc-meta'}, meta)));
  });
  block.append(grid); return block;
}

function sightsPanel(){
  const p = h('section',{class:'panel',id:'panel-sights',role:'tabpanel','aria-labelledby':'tab-sights',hidden:true});
  const w = h('div',{class:'wrap'});
  w.append(panelHead('sights', D.attractions.length+D.dive_sites.length));

  // Subnav
  const subnav = h('div',{class:'subnav'},
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('sights-worth-it')}, I18N.sub.exp[state.lang==='cn'?0:1]),
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('sights-attractions')}, I18N.sub.attr[state.lang==='cn'?0:1]),
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('sights-diving')}, I18N.sub.dive[state.lang==='cn'?0:1])
  );
  w.append(subnav);

  w.append(keyExpBlock());
  w.append(poiGroupBlock('attractions', 'sights-attractions'));
  w.append(poiGroupBlock('dive_sites', 'sights-diving'));
  p.append(w); return p;
}

/* ---------- transport ---------- */
function transfersBlock(){
  const block = h('div',{class:'block reveal', id:'trans-transfers'});
  block.append(h('div',{class:'module-head'},h('h3',{class:'serif'},t('transfers')),
    h('span',{},D.transport.length+' '+t('items'))));
  D.transport.forEach((x,i)=>{
    const status = x[16]||'unverified';
    const sm = I18N.status[status] || I18N.status.unverified;
    const badgeCls = status==='on_demand' ? 'badge-info' : (x[11]==='verified'?'badge-ok':'badge-warn');
    const det = h('details',{class:'tp-branch', open:i===0});
    
    const transName = tr(x[0], D.en_text_replacements?.[x[0]]);
    const transMode = tr(x[1], D.en_text_replacements?.[x[1]]);
    const duration = x[4]||'';
    const price = x[3] ? (' · '+money(x[3])) : '';
    const operator = x[2]||'';
    const fromLoc = tr(x[12], D.en_text_replacements?.[x[12]]);
    const toLoc = tr(x[13], D.en_text_replacements?.[x[13]]);

    det.append(h('summary',{},
      h('span',{class:'tp-index'},String(i+1).padStart(2,'0')),
      h('span',{class:'tp-title'},
        h('small',{}, [transMode, duration, price].filter(Boolean).map(loc).join(' ')),
        h('b',{}, transName)),
      h('span',{class:'badge '+badgeCls}, sm[state.lang==='cn'?0:1]),
      h('span',{class:'branch-toggle'},'+')));
      
    const rawFromLoc = x[12] || '';
    const rawToLoc = x[13] || '';
    const fromNode = D.transport_nodes?.find(n => n.name === rawFromLoc);
    const toNode = D.transport_nodes?.find(n => n.name === rawToLoc);
    const fromDest = fromNode?.place || fromNode?.destination || '';
    const toDest = toNode?.place || toNode?.destination || '';
    const fromEnName = fromNode?.name_en || null;
    const toEnName = toNode?.name_en || null;

    const body = h('div',{class:'tp-body'});
    body.append(h('div',{class:'tp-route'},
      h('div',{},h('small',{},pick('出发','From')),h('b',{},fromLoc),mapLinks(rawFromLoc || fromLoc, x[6], fromDest, fromEnName)),
      h('span',{class:'ar'},'→'),
      h('div',{},h('small',{},pick('抵达','To')),h('b',{},toLoc),mapLinks(rawToLoc || toLoc, x[7], toDest, toEnName))));
      
    // 动作链接（官方时刻表 / 官方预订 / 本地应用 / 搜索）
    const tLinks = getTransportLinks(operator, transName, x[20], x[21]);
    const actions = h('div',{class:'tp-actions'});
    tLinks.forEach(tl=>{
      actions.append(h('a',{class:'tp-btn',href:tl.url,target:'_blank',rel:'noopener noreferrer'}, tl.label));
    });
    body.append(actions);

    if (x[22]) body.append(h('div',{class:'tp-times'}, h('b',{},pick('去程班次：','Outbound: ')), tr(x[22], D.en_text_replacements?.[x[22]])));
    if (x[23]) body.append(h('div',{class:'tp-times'}, h('b',{},pick('返程班次：','Return: ')), tr(x[23], D.en_text_replacements?.[x[23]])));

    body.append(h('dl',{class:'tp-dl'},
      h('div',{},h('dt',{},pick('运营方','Operator')),h('dd',{},
        operator ? h('a',{href:`https://www.google.com/search?q=${encodeURIComponent(operator + ' ' + (D.country_en||''))}`,target:'_blank',rel:'noopener noreferrer'}, operator) : '–')),
      h('div',{},h('dt',{},pick('班次/备注','Schedule / note')),h('dd',{},joinLoc(x[5], x[8]))),
      x[9] ? h('div',{},h('dt',{},pick('预留缓冲','Buffer time')),h('dd',{},tr(x[9], D.en_text_replacements?.[x[9]]))) : null,
      x[10] ? h('div',{},h('dt',{},pick('柜台指引','Station / Counter')),h('dd',{},tr(x[10], D.en_text_replacements?.[x[10]]))) : null,
      h('div',{},h('dt',{},pick('核验状态','Verification')),h('dd',{},joinLoc(x[11])+' · '+t('updated')+' '+(x[19]||''))),
      h('div',{},h('dt',{},pick('出行方式','Mode')),h('dd',{},tr(x[15]||x[1], D.en_text_replacements?.[x[15]])))));
    det.append(body); block.append(det);
  });
  return block;
}

function nodesBlock(){
  const nodes = D.transport_nodes;
  const ng = new Map();
  nodes.forEach(n=>{ const p=n.place||n.destination; if(!ng.has(p))ng.set(p,[]); ng.get(p).push(n); });
  const block = h('div',{class:'block reveal', id:'trans-nodes'});
  block.append(h('div',{class:'module-head'},h('h3',{class:'serif'},t('nodes')),
    h('span',{},nodes.length+' '+t('items'))));
  const groups = h('div',{class:'node-groups'});
  [...ng].forEach(([p,items])=>{
    const g = h('div',{class:'node-group'},h('h4',{}, tr(p, D.en_text_replacements?.[p])));
    items.forEach(n=>{
      const nodeName = tr(n.name, n.name_en);
      g.append(h('div',{class:'node-row'},
        h('div',{},h('b',{}, nodeName),h('small',{},tr(n.type, D.en_text_replacements?.[n.type]))),
        mapLinks(n.name, n.coords, p, n.name_en)));
    });
    groups.append(g);
  });
  block.append(groups); return block;
}

function transportPanel(){
  const p = h('section',{class:'panel',id:'panel-transport',role:'tabpanel','aria-labelledby':'tab-transport',hidden:true});
  const w = h('div',{class:'wrap'});
  w.append(panelHead('transport', D.transport.length));

  // Subnav
  const subnav = h('div',{class:'subnav'},
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('trans-transfers')}, I18N.sub.transfers[state.lang==='cn'?0:1]),
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('trans-nodes')}, I18N.sub.nodes[state.lang==='cn'?0:1])
  );
  w.append(subnav);

  w.append(transfersBlock());
  w.append(nodesBlock());
  p.append(w); return p;
}

/* ---------- budget (中英双币即时换算 CNY/USD) ---------- */
function budgetPanel(){
  const p = h('section',{class:'panel',id:'panel-budget',role:'tabpanel','aria-labelledby':'tab-budget',hidden:true});
  const w = h('div',{class:'wrap'});
  const r = currentRoute(), total = getRouteTotalCny(D.route_budgets?.[r[0]]);
  w.append(panelHead('budget'));

  // Subnav
  const subnav = h('div',{class:'subnav'},
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('budget-overview')}, I18N.sub.b_overview[state.lang==='cn'?0:1]),
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('budget-daily')}, I18N.sub.b_daily[state.lang==='cn'?0:1])
  );
  w.append(subnav);

  const avg = total ? Math.round(total / (D.budget.length || 1)) : 0;
  // V5-B：汇率状态是读者看得见的事实，不是代码内部的巧合。data-rate-state 由 visual_qa 与
  // dataset 投影对账；未登记时必须出现提示文案，且金额保持人民币原样（不得凭空出 $ 数字）。
  const fxStatus = fxState();
  const fxNote = fxStatus === 'VERIFIED'
    ? fxCopy('notice_verified_prefix') + (((D.budget_fx || {}).rate_source) || '') +
      '（' + (((D.budget_fx || {}).rate_date) || '') + '）'
    : fxCopy('notice_unregistered');
  const strip = h('div',{class:'budget-strip reveal', id:'budget-overview',
                        dataset:{rateState: fxStatus, rateNote: '1'}},
    h('div',{class:'bs-num'},h('small',{},t('from_pp')),h('b',{}, money(total))),
    h('div',{class:'bs-num'},h('small',{},I18N.daily_avg[state.lang==='cn'?0:1]),h('b',{}, money(avg))),
    h('p',{}, t('budget_note')),
    h('p',{class:'rate-note','data-rate-state':fxStatus}, fxNote));
  w.append(strip);

  const isPrimaryRoute = (r[0] === (D.routes?.[0]?.[0] || ''));
  if (isPrimaryRoute && Array.isArray(D.budget) && D.budget.length > 0){
    const block = h('div',{class:'block reveal', id:'budget-daily'});
    block.append(h('div',{class:'module-head'},h('h3',{class:'serif'},t('budget_detail')),
      h('span',{},D.budget.length+' '+t('items'))));
    const cards = h('div',{class:'day-cards'});
    const cats=[['stay',3],['food_cat',4],['transit_cat',5],['fun',6],['other',7]];
    D.budget.forEach((b, idx)=>{
      const split = h('div',{class:'dc-split'});
      cats.forEach(([lab,col])=>{
        const val = Number(b[col]);
        const shown = !val ? '–'
          : (state.lang === 'cn' ? '¥' + val.toLocaleString()
                                 : (usdAmount(val) || '¥' + val.toLocaleString()));
        split.append(h('div',{}, h('b',{}, shown), h('span',{}, t(lab))));
      });
      const dNum = parseDayNum(b[0], idx + 1);
      const isTbd = isDateTBD(b[1]);
      cards.append(h('div',{class:'day-card'},
        h('div',{class:'dc-top'},
          h('span',{class:'dc-no'}, I18N.day_tag[state.lang==='cn'?0:1]+dNum),
          h('b',{}, money(b[8]))),
        h('div',{class:'dc-plan'}, (() => {
          const rawPlan = b[2] || '';
          let planEn = D.en_text_replacements?.[rawPlan] || '';
          if (!planEn && /走廊巡礼\s*Day\s*(\d+)/i.test(rawPlan)) planEn = rawPlan.replace(/走廊巡礼\s*Day\s*(\d+)/i, 'Corridor Tour Day $1');
          if (!planEn && /第\s*(\d+)\s*天/i.test(rawPlan)) planEn = rawPlan.replace(/第\s*(\d+)\s*天/i, 'Day $1');
          // 同上：day-card 的 plan 槽以前根本不查词典，缺译就把中文印到 EN 页且不登记缺口。
          // loc() 是唯一实现（tr + 登记 + marker），这里不重复调 visibleText()。
          return state.lang === 'cn' ? rawPlan : (planEn || loc(rawPlan));
        })()),
        isTbd ? null : h('div',{class:'dc-date'}, loc(b[1])),
        split));
    });
    block.append(cards); w.append(block);
  } else {
    w.append(h('div',{class:'block reveal','text':t('detail_only_route1')}));
  }
  p.append(w); return p;
}

/* ---------- toolkit (外露直接下载胶囊 + 官方直达逻辑) ---------- */
function appBadge(status){
  const m = I18N.app_status[status] || ['','','badge-info'];
  return h('span',{class:'badge '+m[2]}, m[state.lang==='cn'?0:1]);
}

function essentialBlock(){
  const apps = D.local_apps.filter(a=>a.availability_status!=='retired' && a.priority==='essential');
  const block = h('div',{class:'block reveal', id:'tool-essential'});
  block.append(h('div',{class:'module-head'},h('h3',{class:'serif'},t('essential')),
    h('span',{},apps.length+' '+t('items'))));
  const grid = h('div',{class:'app-grid'});
  apps.forEach(a=>{
    const foot = h('div',{class:'ac-foot'}, appBadge(a.availability_status));
    
    // 直达应用商店
    if (a.ios_url) foot.append(h('a',{class:'app-btn',href:a.ios_url,target:'_blank',rel:'noopener noreferrer'},t('appstore')));
    if (a.android_url) foot.append(h('a',{class:'app-btn',href:a.android_url,target:'_blank',rel:'noopener noreferrer'},t('gplay')));

    // 官方直达逻辑：若没有原生移动App，官网就是最主要的申报/直达通道；若已有移动App，官网降为次级链接
    if (a.official_url){
      const isWebOnly = !a.ios_url && !a.android_url;
      const btnClass = isWebOnly ? 'app-btn' : 'app-btn alt';
      const btnText = isWebOnly ? t('official') : t('official_sub');
      foot.append(h('a',{class:btnClass,href:a.official_url,target:'_blank',rel:'noopener noreferrer'}, btnText));
    }

    const limits = (state.lang==='cn'?a.limitations_cn:a.limitations_en);
    grid.append(h('div',{class:'app-card2'},
      h('div',{class:'ac-top'},
        h('span',{class:'app-cat'}, catLabel(a.category)),
        h('span',{class:'app-name'}, pick(a.name,a.name_en))),
      h('p',{}, t('use_cases')+(state.lang==='cn'?a.use_cases_cn:a.use_cases_en).join(' · ')),
      limits && limits.length ? h('div',{class:'ac-limits'}, t('limits')+limits.join('；')) : null,
      foot));
  });
  block.append(grid); return block;
}

function ondemandBlock(){
  const apps = D.local_apps.filter(a=>a.availability_status!=='retired' && a.priority!=='essential');
  const block = h('div',{class:'block reveal', id:'tool-ondemand'});
  block.append(h('div',{class:'module-head'},h('h3',{class:'serif'},t('ondemand')),
    h('span',{},apps.length+' '+t('items'))));
  const groups = {
    mobility:[['ride_hailing','maps_navigation','urban_transit'],pick('出行与交通','Mobility & transit')],
    dining:[['food_discovery','food_delivery'],pick('餐饮','Dining')],
    booking:[['intercity_booking','activities_booking','accommodation_booking'],pick('票务与预订','Booking')],
    comms:[['communication','translation','currency_payment','weather_environment'],pick('通讯与工具','Comms & utilities')],
    official:[['official_tourism','safety_emergency'],pick('官方与应急','Official & emergency')]
  };
  let i=0;
  Object.values(groups).forEach(([cats,label])=>{
    const ga = apps.filter(a=>cats.includes(a.category));
    if (!ga.length) return;
    const det = h('details',{class:'app-drawer', open:i===0});
    det.append(h('summary',{},h('b',{},label),h('small',{},ga.length+' '+t('items')),h('span',{class:'branch-toggle'},'+')));
    const mini = h('div',{class:'mini-apps'});
    ga.forEach(a=>{
      const mActions = h('div',{class:'mini-app-actions'});
      // 关键改造：在场景工具卡片表面直接外露应用商店直达胶囊，免点开深层抽屉寻找
      if (a.ios_url) mActions.append(h('a',{class:'mini-btn',href:a.ios_url,target:'_blank',rel:'noopener noreferrer'}, 'App Store ↗'));
      if (a.android_url) mActions.append(h('a',{class:'mini-btn',href:a.android_url,target:'_blank',rel:'noopener noreferrer'}, 'Google Play ↗'));
      if (a.official_url){
        mActions.append(h('a',{class:'mini-btn',href:a.official_url,target:'_blank',rel:'noopener noreferrer'}, pick('官网 ↗','Official ↗')));
      }

      mini.append(h('div',{class:'mini-app'},
        h('div',{class:'mini-app-top'},
          h('b',{}, pick(a.name,a.name_en)),
          appBadge(a.availability_status)),
        h('small',{}, (state.lang==='cn'?a.use_cases_cn:a.use_cases_en).join(' · ')),
        mActions));
    });
    det.append(mini); block.append(det); i++;
  });
  return block;
}

function toolkitPanel(){
  const p = h('section',{class:'panel',id:'panel-toolkit',role:'tabpanel','aria-labelledby':'tab-toolkit',hidden:true});
  const w = h('div',{class:'wrap'});
  w.append(panelHead('toolkit', D.local_apps.length));

  // Subnav
  const subnav = h('div',{class:'subnav'},
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('tool-essential')}, I18N.sub.essential[state.lang==='cn'?0:1]),
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('tool-ondemand')}, I18N.sub.ondemand[state.lang==='cn'?0:1])
  );
  w.append(subnav);

  w.append(essentialBlock());
  w.append(ondemandBlock());
  p.append(w); return p;
}

/* ---------- notes ---------- */
function knowledgeBlock(){
  const rows = D.local_knowledge;
  const block = h('div',{class:'block deep reveal', id:'notes-knowledge'});
  block.append(h('div',{class:'module-head'},h('h3',{class:'serif'},t('knowledge')),
    h('span',{},rows.length+' '+t('items'))));
  const grid = h('div',{class:'num-grid'});
  rows.forEach((k,i)=>grid.append(h('div',{class:'num-card'},
    h('span',{class:'n'},String(i+1).padStart(2,'0')),
    h('small',{}, pick('当地要点','Local')),
    h('h4',{}, tr(k[0], k[1])),
    h('p',{}, tr(k[2], k[3])),
    h('span',{class:'nc-meta'}, tr(k[4], k[5])))));
  block.append(grid); return block;
}

function practicalBlock(){
  const block = h('div',{class:'block reveal', id:'notes-practical'});
  block.append(h('div',{class:'module-head'},h('h3',{class:'serif'},t('practical'))));
  D.practical.forEach((p,i)=>{
    const det = h('details',{class:'note-details', open:i===0});
    det.append(h('summary',{},h('b',{},tr(p[0], D.en_text_replacements?.[p[0]])),h('small',{},'')));
    det.append(h('div',{class:'nd-body'}, linkify(tr(p[1], D.en_text_replacements?.[p[1]]))));
    block.append(det);
  });
  return block;
}

function packingBlock(){
  const pgroups = new Map();
  D.packing.forEach(x=>{ if(!pgroups.has(x[0]))pgroups.set(x[0],[]); pgroups.get(x[0]).push(x); });
  const block = h('div',{class:'block reveal', id:'notes-packing'});
  block.append(h('div',{class:'module-head'},h('h3',{class:'serif'},t('packing')),
    h('span',{},D.packing.length+' '+t('items'))));
  let pi=0;
  [...pgroups].forEach(([cat,items])=>{
    const det = h('details',{class:'note-details', open:pi===0});
    det.append(h('summary',{},h('b',{},tr(cat, D.en_text_replacements?.[cat])),h('small',{},items.length+' '+t('items')),h('span',{class:'branch-toggle'},'+')));
    const body = h('div',{class:'nd-body'});
    items.forEach(x=>body.append(h('div',{style:'padding:6px 0;border-bottom:1px dashed #e4e8ea'},
      h('b',{style:'font-size:12px'}, tr(x[1], x[2])),
      ' — ', joinLoc(x[3], x[6]))));
    det.append(body); block.append(det); pi++;
  });
  return block;
}

function sourcesBlock(){
  const rows = D.source_records || [];
  const status = D.source_ledger_status || 'absent';
  const block = h('div',{'class':'block reveal', 'id':'notes-sources', 'data-module':'source_evidence',
                         'data-se-ledger-status':status, 'data-se-rows':String(rows.length)});
  block.append(h('div',{class:'module-head'},h('h3',{class:'serif'},t('sources')),
    h('span',{},rows.length+' '+t('items'))));
  if (status !== 'projected') {
    // #113：台账缺失时不再印一张空表冒充「0 条已核验」——显式说明，正式门据此阻断。
    // 这句是**读者界面自己的话**（UI chrome），不是实体内容，所以两档都必须是登记过的：
    // 中文档印中文，候审档的英文态印英文。h() 的子串会走 visibleText→tr()，
    // 未登记的中文串在英文态会变成显式 pending 并计入 UNTRANSLATED——那是尺子在响，不是装饰。
    block.append(h('div',{'class':'src-absent', 'role':'alert'},
      tr('本页未随附可审计的来源台账（source_evidence_meta 缺失或为空）；中文正式门把这种情况判为阻断，不印空表。',
         'No auditable source ledger is attached to this page (source_evidence_meta is missing or empty); '
         + 'the Chinese formal gate treats this as blocked and prints no empty table.')));
    return block;
  }
  const verified = rows.filter(r=>r.verification_status==='verified').length;
  const providers = new Set(rows.map(r=>r.source_provider)).size;
  block.append(h('div',{class:'src-stats'},
    h('div',{class:'src-stat'},h('b',{'data-se-count':'total'},rows.length.toLocaleString()),h('span',{},t('sources_total'))),
    h('div',{class:'src-stat'},h('b',{'data-se-count':'verified'},verified.toLocaleString()),h('span',{},t('verified'))),
    h('div',{class:'src-stat'},h('b',{'data-se-count':'providers'},String(providers)),h('span',{},t('providers')))));
  const byStatus = new Map();
  rows.forEach(r=>{const k=r.verification_status;if(!byStatus.has(k))byStatus.set(k,[]);byStatus.get(k).push(r);});
  const wrap = h('div',{class:'source-groups'});
  [...byStatus].forEach(([st,items])=>{
    const det = h('details',{class:'note-details'});
    // 中文档印注册表里的中文标签；候审档的英文态印机器枚举原值（verified），
    // 不给它编一个没登记的英文译名——显示面的翻译只能来自注册表，不能来自这里的一句字面量。
    det.append(h('summary',{},h('b',{},(state.lang === 'cn' && items[0] && items[0].verification_label) || st),
      h('small',{},items.length+' '+t('items')),h('span',{class:'branch-toggle'},'+')));
    const body = h('div',{class:'nd-body'});
    // 零丢弃：整组逐条渲染。旧的 slice(0,15)＋「… N more」没有下文，
    // CA 174 条、PH 365 条来源记录因此在读者页面上根本不存在（#113 静默丢记录）。
    items.forEach(r=>body.append(h('div',{'class':'se-row', 'data-se-index':String(r.row_index),
                                          'data-se-uid':String(r.row_uid)},
      h('b',{style:'font-size:11.5px'},r.destination+' · '+r.name),
      h('div',{},h('small',{'class':'se-meta'},r.source_provider+' · '+r.retrieved_at+' · '
        + (state.lang === 'cn'
           ? (r.evidence_level_label || '未登记等级')
           : (r.evidence_level || 'level-unregistered')))),
      h('a',{href:r.url,target:'_blank',rel:'noopener noreferrer',style:'font-size:10px;word-break:break-all'},r.url))));
    det.append(body); wrap.append(det);
  });
  block.append(wrap);
  return block;
}

function notesPanel(){
  const p = h('section',{class:'panel',id:'panel-notes',role:'tabpanel','aria-labelledby':'tab-notes',hidden:true});
  const w = h('div',{class:'wrap'});
  w.append(panelHead('notes', D.local_knowledge.length));

  // Subnav
  const subnav = h('div',{class:'subnav'},
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('notes-knowledge')}, I18N.sub.knowledge[state.lang==='cn'?0:1]),
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('notes-practical')}, I18N.sub.practical[state.lang==='cn'?0:1]),
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('notes-packing')}, I18N.sub.packing[state.lang==='cn'?0:1]),
    h('button',{class:'subnav-btn',onclick:()=>scrollToId('notes-sources')}, I18N.sub.sources[state.lang==='cn'?0:1])
  );
  w.append(subnav);

  w.append(knowledgeBlock());
  w.append(practicalBlock());
  w.append(packingBlock());
  w.append(sourcesBlock());
  p.append(w); return p;
}

/* ---------- footer ---------- */
function renderFooter(){
  const dates = (D.source_records || []).map(s=>s.retrieved_at).filter(x=>/^\d{4}-\d{2}-\d{2}$/.test(x)).sort();
  const f = document.getElementById('footer-inner');
  f.innerHTML='';
  f.append(h('span',{}, 'Travel-Scope · '+pick(D.country,D.country_en)+' · '+(dates.at(-1)||'')),
    h('span',{}, t('demo')));
}

/* ---------- tabs & navigation ---------- */
const TAB_IDS = ['overview','stays','food','sights','transport','budget','toolkit','notes'];
function renderTabs(){
  const c = document.getElementById('tabs');
  c.innerHTML='';
  TAB_IDS.forEach(id=>{
    const isSelected = id === state.tab;
    c.append(h('button',{type:'button',role:'tab',id:'tab-'+id,
      'aria-selected':isSelected,
      'aria-controls':'panel-'+id,
      tabindex:isSelected ? '0' : '-1',
      dataset:{target:id},
      onclick:()=>selectTab(id,true)},
      I18N.ch[id][state.lang==='cn'?0:1]));
  });
  if (!c.dataset.keyboardBound){
    c.dataset.keyboardBound = '1';
    c.addEventListener('keydown', e => {
      const tabs = Array.from(c.querySelectorAll('[role="tab"]'));
      const currentIndex = tabs.findIndex(tab => tab.dataset.target === state.tab);
      if (currentIndex === -1) return;
      let nextIndex = null;
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown'){
        nextIndex = (currentIndex + 1) % tabs.length;
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp'){
        nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
      } else if (e.key === 'Home'){
        nextIndex = 0;
      } else if (e.key === 'End'){
        nextIndex = tabs.length - 1;
      }
      if (nextIndex !== null){
        e.preventDefault();
        const targetTab = tabs[nextIndex];
        selectTab(targetTab.dataset.target, false);
        targetTab.focus();
      }
    });
  }
}
function selectTab(id, scrollTo){
  state.tab = id;
  document.querySelectorAll('#main .panel').forEach(p=>
    p.hidden = p.id !== 'panel-'+id);
  document.querySelectorAll('#tabs button').forEach(b=>{
    const isSelected = b.dataset.target === id;
    b.setAttribute('aria-selected', isSelected ? 'true' : 'false');
    b.setAttribute('tabindex', isSelected ? '0' : '-1');
    if (isSelected){
      b.scrollIntoView({inline:'center',block:'nearest',behavior:reduced?'auto':'smooth'});
    }
  });
  const activePanel = document.getElementById('panel-'+id);
  if (activePanel){
    activePanel.querySelectorAll('img').forEach(img=>{
      if (img.style.opacity === '0') img.style.opacity = '1';
    });
  }
  if (scrollTo){
    const main = document.getElementById('main');
    if (main.getBoundingClientRect().top > 8){
      main.scrollIntoView({behavior:reduced?'auto':'smooth',block:'start'});
    }
  }
}
function chooseRoute(routeName){
  state.route = routeName;
  state.tab = 'overview';
  renderAll();
  const main = document.getElementById('main');
  main.scrollIntoView({behavior:reduced?'auto':'smooth',block:'start'});
}

function scrollToId(id){
  const el = document.getElementById(id);
  if (el){
    el.scrollIntoView({behavior:reduced?'auto':'smooth',block:'start'});
  }
}

/* ---------- reveals motion ---------- */
let io;
function setupReveals(){
  if (io) io.disconnect();
  const nodes = document.querySelectorAll('.reveal');
  if (reduced || !('IntersectionObserver' in window)){ nodes.forEach(n=>n.classList.add('is-revealed')); return; }
  io = new IntersectionObserver(es=>es.forEach(e=>{ if(e.isIntersecting){ e.target.classList.add('is-revealed'); io.unobserve(e.target);} }),
    {rootMargin:'0px 0px -8% 0px'});
  nodes.forEach(n=>io.observe(n));
}

/* ---------- Smart Scroll Navbar 监听器 (0.2s 快速滑出) ---------- */
function updateTopbarVisibility(){
  const topbar = document.getElementById('topbar');
  if (!topbar) return;
  // V4.2.0: 确保首屏 scrollY=0 时顶栏常驻可见，语言切换按钮随时可触达
  topbar.classList.add('is-visible');
}

/* ---------- render all ---------- */
/* v4.2.1 SS2.2.6 + SS2.2.4: language chrome must follow the state, not stay zh-CN forever. */
function syncDocumentChrome(){
  const isCn = state.lang === 'cn';
  document.documentElement.lang = isCn ? 'zh-CN' : 'en';
  const country = isCn ? (D.country || D.country_en || 'Travel-Scope')
                       : (D.country_en || D.country || 'Travel-Scope');
  const route = currentRoute();
  let title = 'Travel-Scope \u00b7 ' + country + (isCn ? '\u65c5\u884c\u653b\u7565' : ' Travel Guide');
  if (!isCn && route) {
    const routeEn = usableName(route[1]) || usableName(route[0]);
    if (routeEn) title += ' \u2014 ' + routeEn;
  }
  document.title = title;
}

function renderAll(){
  syncDocumentChrome();
  renderCover();
  renderTabs();
  const main = document.getElementById('main');
  main.innerHTML='';
  main.append(
    overviewPanel(), staysPanel(), foodPanel(), sightsPanel(),
    transportPanel(), budgetPanel(), toolkitPanel(), notesPanel());
  document.querySelectorAll('#main .panel').forEach(p=>
    p.hidden = p.id !== 'panel-'+state.tab);
  renderFooter();
  if (state.lang === 'en') {
    const pending = [...new Set(UNTRANSLATED)];
    document.documentElement.dataset.enUntranslated = String(pending.length);
    document.documentElement.dataset.enUntranslatedSample = JSON.stringify(pending.slice(0, 12));
    // The gate needs the whole清册, not a 12-item teaser: without it, "151 pending" is a number
    // nobody can act on. Capped so a pathological page cannot bloat the DOM.
    document.documentElement.dataset.enUntranslatedList = JSON.stringify(pending.slice(0, 400));
  }
  setupReveals();
  updateTopbarVisibility();
}

/* ---------- boot ---------- */
window.addEventListener('scroll', updateTopbarVisibility, { passive: true });
// ZH-RELEASE-1：正式（zh-formal）交付物不渲染这颗按钮 ⇒ 语言在功能层面不可切换；
// en-audit 探针页仍带按钮，英文通道的真渲染证据继续由它出。档位由渲染器按合同决定，
// 这里不许自己判断「现在是不是正式档」。
const langToggle = document.getElementById('lang-btn');
if (langToggle) langToggle.addEventListener('click',()=>{
  state.lang = state.lang==='cn'?'en':'cn';
  renderAll();
});
renderAll();
})();
