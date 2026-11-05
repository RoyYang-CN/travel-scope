(()=>{'use strict';
const payload=JSON.parse(document.getElementById('travel-data').textContent), config=payload.contract;
let lang=payload.editions.cn?'cn':'en', tab=config.tabs[0].id, route='', transitionSerial=0;
const $=id=>document.getElementById(id), text=(cn,en)=>lang==='cn'?cn:en;
const reducedMotion=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const current=()=>payload.editions[lang];
function translated(s){return lang==='en'?(current().en_text_replacements?.[s]??s):s;}
function name(row){return row[lang==='en'?2:1]||row[1]||'';}
function mapIdentity(label,context){
 const country=lang==='en'?(current().country_en||current().country):(current().country||current().country_en);
 return [...new Set([label,context,country].map(value=>String(value||'').trim()).filter(Boolean))].join(', ');
}
function validCoords(coords){
 const parts=String(coords||'').split(',').map(value=>Number(value.trim()));
 return parts.length===2&&Number.isFinite(parts[0])&&Number.isFinite(parts[1])&&Math.abs(parts[0])<=90&&Math.abs(parts[1])<=180?parts:null;
}
function placeIdFor(row){
 const ids=current().google_place_ids||{},place=String(row[0]||'').trim();
 for(const candidate of [`${place}|${row[1]||''}`,`${place}|${row[2]||''}`,row[1],row[2]]){
  const value=ids[candidate];if(typeof value==='string'&&/^ChIJ[A-Za-z0-9_-]{15,}$/.test(value))return value;
 }
 return '';
}
function mapTarget(label,context,coords){
 const targets=current().map_targets||{},replacements=current().en_text_replacements||{};
 const invKeys=lang==='en'?Object.keys(replacements).filter(k=>replacements[k]===label):[];
 const wanted=[label,translated(label),...invKeys].map(value=>String(value||'').trim().toLowerCase());
 const direct=targets[`${context||''}|${label||''}`]||targets[label]||invKeys.map(k=>targets[`${context||''}|${k}`]||targets[k]).find(Boolean);if(direct&&typeof direct==='object')return direct;
 const candidates=Object.values(targets).filter(item=>item&&[item.canonical_name,item.name_en].map(value=>String(value||'').trim().toLowerCase()).some(value=>wanted.includes(value)));
 const contextual=candidates.find(item=>!context||[item.destination,item.destination_en].map(value=>String(value||'').trim().toLowerCase()).includes(String(context).trim().toLowerCase()));
 const point=validCoords(coords),coordinateMatch=point&&candidates.find(item=>{const candidate=validCoords(item.coords);return candidate&&Math.abs(candidate[0]-point[0])<.00005&&Math.abs(candidate[1]-point[1])<.00005;});
 const coordTarget=point&&!coordinateMatch&&Object.values(targets).find(item=>{const candidate=validCoords(item.coords);return candidate&&Math.abs(candidate[0]-point[0])<.00005&&Math.abs(candidate[1]-point[1])<.00005;});
 return contextual||coordinateMatch||coordTarget||(candidates.length===1?candidates[0]:null);
}
function maps(label,coords,placeId,context){
 const platforms=config.map_platforms[current().is_overseas===false?'domestic':'international'];
 const target=mapTarget(label,context,coords)||{},level=target.target_level||'search_candidate';
 const identity=mapIdentity(target.canonical_name||label,target.destination||context),query=encodeURIComponent(identity),point=validCoords(target.coords||coords);
 const validPlaceId=level==='verified_place_id'&&/^ChIJ[A-Za-z0-9_-]{15,}$/.test(String(target.google_place_id||placeId||''));
 const coordinateParam=(level==='verified_coordinate'||!validPlaceId)&&point?'&ll='+point.join(','):'';
 const urls={google:level==='verified_platform_url'&&target.google_url?target.google_url:'https://www.google.com/maps/search/?api=1&query='+query+(validPlaceId?'&query_place_id='+encodeURIComponent(target.google_place_id||placeId):coordinateParam),apple:level==='verified_platform_url'&&target.apple_url?target.apple_url:'https://maps.apple.com/?q='+query+(point?'&ll='+point.join(','):''),amap:target.amap_url||(point&&level==='verified_coordinate'?'https://uri.amap.com/marker?position='+point[1]+','+point[0]+'&name='+encodeURIComponent(target.canonical_name||label)+'&coordinate=wgs84&callnative=0':'https://uri.amap.com/search?keyword='+query),baidu:target.baidu_url||(point&&level==='verified_coordinate'?'https://api.map.baidu.com/marker?location='+point[0]+','+point[1]+'&title='+encodeURIComponent(target.canonical_name||label)+'&content='+query+'&output=html&coord_type=wgs84':'https://map.baidu.com/search/'+query)};
 const labels={google:'Google Maps',apple:'Apple Maps',amap:text('高德地图','Amap'),baidu:text('百度地图','Baidu Maps')};
 const suffix=level==='search_candidate'?text(' 搜索',' Search'):text(' 位置',' Location');
 return '<div class="map-links" data-map-level="'+esc(level)+'">'+platforms.map(p=>'<a target="_blank" rel="noopener noreferrer" href="'+esc(urls[p])+'">'+labels[p]+suffix+' ↗</a>').join('')+'</div>';
}
function fields(row){return (Array.isArray(row)?row:Object.values(row)).filter(v=>v!==null&&v!==undefined&&v!=='');}
function linked(value){const s=String(translated(value));return /^https?:\/\//.test(s)?'<a href="'+esc(s)+'" target="_blank" rel="noopener noreferrer">'+esc(s)+'</a>':esc(s);}
function poi(row,spec){
 const id=placeIdFor(row);
 const publicFields=row.filter((value,index)=>{const visible=String(value||'').trim();return index!==spec.image&&index!==spec.image+1&&index!==spec.coords&&!/未采用聚合平台评分|aggregat(?:e|ed) platform rating/i.test(visible)&&!/^[-+]?\d{1,3}\.\d+\s*,\s*[-+]?\d{1,3}\.\d+$/.test(visible);});
 return '<article class="poi poi-text-only"><div class="poi-copy"><h4>'+esc(name(row))+'</h4><p>'+esc(translated(row[0]))+' · '+esc(translated(row[3]))+'</p>'+maps(name(row),row[spec.coords]||'',typeof id==='string'?id:'',placeLabel(row[0]))+'<details><summary>'+text('规划信息','Planning details')+'</summary><p>'+fields(publicFields).map(linked).join('<br>')+'</p></details></div></article>';
}
function routeName(row){return lang==='en'?(row[7]||translated(row[0])):row[0];}
function routeHTML(rows){
 if(!rows.length)return '';
 if(!route||!rows.some(row=>row[0]===route))route=rows[0][0];
 const active=rows.find(row=>row[0]===route)||rows[0];
 const chooser='<div class="route-switcher" role="group" aria-label="'+text('路线选择','Route selection')+'">'+rows.map((row,index)=>'<button type="button" data-route="'+esc(row[0])+'" aria-pressed="'+(row[0]===route)+'"><small>'+text('路线','Route')+' '+(index+1)+'</small><b>'+esc(routeName(row))+'</b></button>').join('')+'</div>';
 const rawNodes=Array.isArray(active[8])&&active[8].length?active[8]:String(translated(active[2])||'').split(/\s*(?:→|->|—|-|>)\s*/);
 const nodes=rawNodes.map(s=>String(s).trim()).filter(Boolean);
 return chooser+'<article class="route-feature"><div class="route-kicker">'+text(active===rows[0]?'推荐路线':'备选路线',active===rows[0]?'Recommended route':'Alternative route')+'</div><h4>'+esc(routeName(active))+'</h4><div class="route-flow">'+nodes.map((node,index)=>'<span><i>'+(index+1)+'</i>'+esc(node)+'</span>').join('')+'</div><p>'+esc(translated(active[3]))+'</p><dl><div><dt>'+text('节奏','Pace')+'</dt><dd>'+esc(translated(active[4]))+'</dd></div><div><dt>'+text('预算','Budget')+'</dt><dd>'+esc(translated(active[5]))+'</dd></div><div><dt>'+text('交通','Transport')+'</dt><dd>'+esc(translated(active[6]))+'</dd></div></dl></article>';
}
function editorialFigure(item){return '<figure class="editorial-inline"><div class="editorial-visual"><img src="'+esc(item.image)+'" alt="'+esc(lang==='en'?(item.title_en||item.title):item.title)+'" loading="lazy"></div><figcaption><span>'+esc(translated(item.destination))+'</span><b>'+esc(lang==='en'?(item.title_en||item.title):item.title)+'</b><p>'+esc(lang==='en'?(item.caption_en||item.caption):item.caption)+'</p><small>'+text('摄影','Photo')+' '+esc(item.author)+' · '+esc(item.license)+' · <a href="'+esc(item.source_page)+'" target="_blank" rel="noopener noreferrer">'+text('来源','Source')+' ↗</a></small></figcaption></figure>';}
function days(rows){
 const groups=new Map(), lookup=new Map();
 for(const [key,spec] of Object.entries(config.modules))if('image'in spec)for(const r of current()[key]||[])lookup.set(r[1],r[0]);
 const visible=route?rows.filter(row=>row[0]===route):rows;
 for(const row of visible){const key=String(row[1]);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);}
 const entries=[...groups].map(([day,items])=>{
  const areas=[...new Set(items.flatMap(r=>{const exact=lookup.get(r[4]);if(exact)return [exact];if(String(r[3])==='区域')return [r[4]];if(String(r[3])==='交通'){const parts=String(r[4]).split('→');return parts.length>1?[parts.at(-1)]:parts;}return []}).filter(Boolean))];
  const labels=areas.map(a=>{const d=(current().destinations||[]).find(r=>r[0]===a);return lang==='en'&&d?d[1]:a;});
  return {day,items,areas,labels};
 });
 const routeRow=(current().routes||[]).find(r=>r[0]===route), corridor=String(routeRow?.[2]||'');
 const allMedia=current().editorial_media||[],routed=allMedia.filter(item=>item.route===route);
 const media=(routed.length?routed:allMedia.filter(item=>corridor.includes(item.destination)));
 const attachments=new Map(), usedByDestination=new Map();
 media.forEach((item,index)=>{
  const candidates=entries.map((entry,i)=>entry.areas.includes(item.destination)?i:-1).filter(i=>i>=0);
  const seen=usedByDestination.get(item.destination)||0;
  let slot=candidates.length?candidates[Math.min(candidates.length-1,Math.floor(seen*candidates.length/Math.max(1,media.filter(x=>x.destination===item.destination).length)))]:Math.min(entries.length-1,Math.round((index+1)*entries.length/(media.length+1)));
  while(attachments.has(slot)&&slot<entries.length-1)slot++;
  attachments.set(slot,item);usedByDestination.set(item.destination,seen+1);
 });
 return entries.map((entry,index)=>'<article class="day"><div class="day-title"><small>'+esc(entry.day)+'</small><b>'+esc(entry.labels.join(' → ')||text('目的地待确认','Destination pending'))+'</b></div><details><summary>'+text('查看当天安排','View daily plan')+'</summary><ul>'+entry.items.map(r=>'<li>'+esc(translated(r[4]))+' · '+esc(translated(r[3]))+'</li>').join('')+'</ul></details></article>'+(attachments.has(index)?editorialFigure(attachments.get(index)):'')).join('');
}
function editorial(rows){return rows.map(editorialFigure).join('');}
function placeLabel(place){const row=(current().destinations||[]).find(item=>item[0]===place);return lang==='en'?(row?.[1]||translated(place)):place;}
function branchMedia(place,moduleKey){
 const sectionMedia=current().section_media||[];
 const section=sectionMedia.find(item=>item.destination===place&&Array.isArray(item.modules)&&item.modules.includes(moduleKey)&&(!item.primary_module||item.primary_module===moduleKey));
 if(section&&section.image)return {...section,displayRole:section.asset_role||'category_reference'};
 const editorial=(current().editorial_media||[]).find(item=>item.destination===place&&item.image);
 if(moduleKey==='attractions'&&editorial)return {...editorial,focal_point:'50% 50%',displayRole:'destination_context'};
 const atmosphere=sectionMedia.find(item=>item.destination===place&&item.image&&item.asset_role==='destination_atmosphere');
 if(atmosphere)return {...atmosphere,displayRole:'destination_context'};
 if(editorial)return {...editorial,focal_point:'50% 50%',displayRole:'destination_context'};
 const localFeature=sectionMedia.find(item=>item.destination===place&&item.image&&Array.isArray(item.modules)&&item.modules.includes(moduleKey));
 if(localFeature)return {...localFeature,displayRole:'destination_context'};
 return null;
}
function branchSummary(place,count,index,moduleKey){
 const media=branchMedia(place,moduleKey),label=placeLabel(place);
 const visual=media&&media.image?'<span class="branch-visual" data-media-destination="'+esc(media.destination||place)+'" data-media-role="'+esc(media.displayRole||media.asset_role||'destination_context')+'"><img src="'+esc(media.image)+'" alt="'+esc(label)+'" loading="lazy" style="object-position:'+esc(media.focal_point||'50% 50%')+'"><i>'+esc(label)+'</i></span>':'<span class="branch-visual branch-visual-empty"><i>'+esc(label)+'</i></span>';
 return '<summary>'+visual+'<span class="branch-summary-copy"><small>'+text('目的地支线 '+String(index+1).padStart(2,'0'),'Destination branch '+String(index+1).padStart(2,'0'))+'</small><b>'+esc(label)+'</b><em>'+count+text(' 个已核验条目',' verified records')+'</em></span><span class="branch-toggle" aria-hidden="true">+</span></summary>';
}
function poiBranches(rows,spec,moduleKey){
 const groups=new Map();for(const row of rows){const place=row[0];if(!groups.has(place))groups.set(place,[]);groups.get(place).push(row);}
 return '<div class="destination-branches">'+[...groups].map(([place,items],index)=>'<details class="destination-branch" data-destination="'+esc(place)+'" '+(index===0?'open':'')+'>'+branchSummary(place,items.length,index,moduleKey)+'<div class="branch-records">'+items.map(row=>poi(row,spec)).join('')+'</div></details>').join('')+'</div>';
}
function leadCards(rows){return '<div class="lead-cards">'+rows.map(row=>'<article><small>'+esc(placeLabel(row[0]))+'</small><h4>'+esc(name(row))+'</h4><p>'+fields(row).slice(3,7).map(linked).join(' · ')+'</p></article>').join('')+'</div>';}
function highlights(rows){return '<div class="highlight-cards">'+rows.map((row,index)=>'<article><span>'+String(index+1).padStart(2,'0')+'</span><div><small>'+esc(placeLabel(row[0]))+'</small><h4>'+esc(name(row))+'</h4><p>'+fields(row).slice(3,8).map(linked).join(' · ')+'</p></div></article>').join('')+'</div>';}
const scheduleLabels={exact_date_verified:['指定日期已核验','Exact date verified'],published_reference:['有效期内参考班次','Published reference'],on_demand:['按需预约','On demand'],future_unpublished:['未来班次尚未发布','Future schedule unpublished'],unverified:['无法可靠核验','Not reliably verified']};
function scheduleLabel(status,fallback){const labels=scheduleLabels[status];return labels?labels[lang==='en'?1:0]:translated(fallback);}
function scheduleTimes(value,label){const times=String(value||'').split('|').map(item=>item.trim()).filter(Boolean);return times.length?'<section class="schedule-times"><small>'+esc(label)+'</small><div>'+times.map(item=>'<span>'+esc(item)+'</span>').join('')+'</div></section>':'';}
function transportHTML(rows){return '<div class="transport-branches">'+rows.map((row,index)=>{const start=translated(row[12]||String(row[0]).split('→')[0]),end=translated(row[13]||String(row[0]).split('→').at(-1)),status=row[16]||'unverified',effective=lang==='en'?(row[18]||row[17]):row[17],checked=row[19]||'',timetable=row[20]||'',booking=row[21]||'',times=scheduleTimes(row[22],text('去程班次','Outbound departures'))+scheduleTimes(row[23],text('返程班次','Return departures'));const fallbackApp=(current().local_apps||[]).find(a=>['intercity_booking','ride_hailing'].includes(a.category)&&a.availability_status!=='retired');const fallbackUrl=fallbackApp?(fallbackApp.official_url||fallbackApp.ios_url||fallbackApp.android_url):'';const fallbackName=fallbackApp?(lang==='en'?(fallbackApp.name_en||fallbackApp.name):fallbackApp.name):'';const actionLinks=[];if(timetable)actionLinks.push('<a href="'+esc(timetable)+'" target="_blank" rel="noopener noreferrer">'+text('官方时刻表','Official timetable')+' ↗</a>');if(booking)actionLinks.push('<a href="'+esc(booking)+'" target="_blank" rel="noopener noreferrer">'+text('查询或预订','Search / book')+' ↗</a>');if(!actionLinks.length&&fallbackUrl)actionLinks.push('<a href="'+esc(fallbackUrl)+'" target="_blank" rel="noopener noreferrer">'+text('通过 '+fallbackName+' 查询','Search via '+fallbackName)+' ↗</a>');const links=actionLinks.join('');return '<details class="transport-branch" '+(index===0?'open':'')+'><summary><span class="transport-index">'+String(index+1).padStart(2,'0')+'</span><span><small>'+esc(translated(row[1]))+' · '+esc(translated(row[4]))+'</small><b>'+esc(translated(row[0]))+'</b><em class="schedule-status schedule-'+esc(status)+'">'+esc(scheduleLabel(status,row[5]))+'</em></span><span class="branch-toggle" aria-hidden="true">+</span></summary><div class="transport-body"><div class="transport-route"><div><small>'+text('出发','From')+'</small><b>'+esc(start)+'</b>'+maps(start,row[6]||'','')+'</div><i>→</i><div><small>'+text('抵达','To')+'</small><b>'+esc(end)+'</b>'+maps(end,row[7]||'','')+'</div></div>'+times+'<dl><div><dt>'+text('运营与方式','Operator & mode')+'</dt><dd>'+esc(translated(row[2]))+'</dd></div><div><dt>'+text('班次与有效期','Schedule & validity')+'</dt><dd>'+esc(scheduleLabel(status,row[5]))+(effective?' · '+esc(effective):'')+(checked?' · '+text('查询于 ','Checked ')+esc(checked):'')+'</dd></div><div><dt>'+text('规划提醒','Planning note')+'</dt><dd>'+esc(translated(row[8]))+'</dd></div><div><dt>'+text('核验状态','Verification')+'</dt><dd>'+esc(translated(row[11]))+'</dd></div></dl>'+(links?'<div class="transport-source-links">'+links+'</div>':'')+'</div></details>';}).join('')+'</div>';}
function nodeBranches(rows){const groups=new Map();for(const row of rows){const place=row.place||row[0],item=Array.isArray(row)?row:[row.place,row.name,row.name_en,row.type,row.coords,row.source_status];if(!groups.has(place))groups.set(place,[]);groups.get(place).push(item);}return '<div class="node-groups">'+[...groups].map(([place,items])=>'<section><h4>'+esc(placeLabel(place))+'</h4>'+items.map(row=>'<article><div><b>'+esc(lang==='en'?(row[2]||translated(row[1])):row[1])+'</b><small>'+esc(translated(row[3]))+'</small></div>'+maps(lang==='en'?(row[2]||translated(row[1])):row[1],row[4]||'','',placeLabel(place))+'</article>').join('')+'</section>').join('')+'</div>';}
function localKnowledgeHTML(rows){const items=Array.isArray(rows[0])?rows:[rows];return '<div class="tips-lead">'+items.filter(row=>Array.isArray(row)&&row.length).map((row,index)=>'<article><span>'+String(index+1).padStart(2,'0')+'</span><div><small>'+text('旅行要点','Travel essential')+'</small><h4>'+esc(lang==='en'?(row[1]||translated(row[0])):row[0])+'</h4><p>'+esc(lang==='en'?(row[3]||translated(row[2])):row[2])+'</p><em>'+esc(lang==='en'?(row[5]||translated(row[4])):row[4])+'</em></div></article>').join('')+'</div>';}
function tipBranches(rows,kind){return '<div class="tip-branches">'+rows.map((row,index)=>{const title=kind==='packing'?(lang==='en'?(row[2]||translated(row[1])):row[1]):translated(row[0]),category=kind==='packing'?translated(row[0]):text('入境与当地事务','Entry and local practicalities'),details=kind==='packing'?fields(row).slice(3,8):fields(row).slice(1);return '<details '+(index===0?'open':'')+'><summary><span class="tip-index">'+String(index+1).padStart(2,'0')+'</span><span><small>'+esc(category)+'</small><b>'+esc(title)+'</b></span><span class="branch-toggle" aria-hidden="true">+</span></summary><div class="tip-body">'+details.map(value=>'<p>'+linked(value)+'</p>').join('')+'</div></details>';}).join('')+'</div>';}
function amount(value){
 const n=Number(value);
 if(!Number.isFinite(n))return '';
 const bm=current().budget_meta||{};
 const rates=bm.rates||{};
 const isEn=lang==='en';
 if(isEn){
  const rate=rates.USD||(bm.symbol==='$'?1:null);
  if(rate){
   const converted=Math.round(n*rate);
   return '$'+converted.toLocaleString('en-US');
  }
  return (bm.symbol||'$')+n.toLocaleString('en-US');
 }else{
  const rate=rates.CNY||(bm.symbol==='¥'?1:null);
  if(rate){
   const converted=Math.round(n*rate);
   return '¥'+converted.toLocaleString('zh-CN');
  }
  return (bm.symbol||'¥')+n.toLocaleString('zh-CN');
 }
}function budgetHTML(rows){const totals={};for(const row of rows)for(let index=3;index<=8;index++){const value=Number(row[index]);if(Number.isFinite(value))totals[index]=(totals[index]||0)+value;}const grand=totals[8]||[3,4,5,6,7].reduce((sum,index)=>sum+(totals[index]||0),0),average=rows.length?Math.round(grand/rows.length):0,overview='<div class="budget-overview"><span><small>'+text('行程估算','Trip estimate')+'</small><strong>'+amount(grand)+'</strong></span><span><small>'+text('日均估算','Daily average')+'</small><strong>'+amount(average)+'</strong></span><p>'+text('研究期间估算，不是已预订价格；出发前需重新核对交通、住宿与活动价格。','Research-stage estimate, not a booked price. Recheck transport, stays and activities before departure.')+'</p></div>';return overview+'<div class="budget-cards">'+rows.map(row=>{const value=index=>{const n=Number(row[index]);return Number.isFinite(n)?n:(totals[index]||0);},calculated=[3,4,5,6,7].reduce((sum,index)=>sum+value(index),0),total=Number(row[8]),safeTotal=Number.isFinite(total)?total:(totals[8]||calculated);return '<article><div class="budget-card-head"><span><small>'+esc(translated(row[0]))+'</small><b>'+esc(translated(row[2]))+'</b></span><strong>'+amount(safeTotal)+'</strong></div><div class="budget-bars">'+[[text('住宿','Stay'),value(3)],[text('餐饮','Food'),value(4)],[text('交通','Transport'),value(5)],[text('活动','Activities'),value(6)],[text('其他','Other'),value(7)]].map(item=>'<span><i>'+esc(item[0])+'</i><b>'+amount(item[1])+'</b></span>').join('')+'</div><p>'+esc(translated(row[1]))+'</p></article>';}).join('')+'</div>';}
function appShortcuts(cats,title,moduleKey){
 const apps=(current().local_apps||[]).filter(a=>cats.includes(a.category)&&a.availability_status!=='retired'&&a.availability_status!=='pending');
 if(!apps.length)return '';
 const modAttr=moduleKey?' data-module="'+esc(moduleKey)+'"':'';
 if(apps.length===1){
  const a=apps[0],appName=esc(lang==='en'?(a.name_en||a.name):a.name),url=esc(a.official_url||a.ios_url||a.android_url||'#');
  return '<div class="app-capsule-bar"'+modAttr+'><a href="'+url+'" target="_blank" rel="noopener noreferrer" class="app-capsule app-capsule-single"><span class="app-capsule-label">'+esc(title)+'</span><b class="app-capsule-name">'+appName+(a.availability_status==='conditional'?' <i>⚠️</i>':'')+' ↗</b></a></div>';
 }
 const shown=apps.slice(0,3);
 const pills=shown.map(a=>{
  const appName=esc(lang==='en'?(a.name_en||a.name):a.name),url=esc(a.official_url||a.ios_url||a.android_url||'#');
  return '<a href="'+url+'" target="_blank" rel="noopener noreferrer" class="app-capsule"><span class="app-capsule-name">'+appName+(a.availability_status==='conditional'?' <i>⚠️</i>':'')+' ↗</span></a>';
 }).join('');
 const moreBtn=apps.length>3?'<button type="button" class="app-capsule app-capsule-more" onclick="activateTab(\'local_toolkit\')">'+text('查看全部 ('+apps.length+') ↗','View all ('+apps.length+') ↗')+'</button>':'';
 return '<div class="app-capsule-bar"'+modAttr+'><span class="app-capsule-label">'+esc(title)+'</span>'+pills+moreBtn+'</div>';
}
function localAppsHTML(apps){
 const active=(apps||[]).filter(a=>a.availability_status!=='retired'&&a.availability_status!=='pending');
 if(!active.length)return '<p class="empty">'+text('暂无已核验在地工具；未用演示内容填充。','No verified local apps; no filler added.')+'</p>';
 const categories={
  ride_hailing:[text('叫车与接送机','Ride-Hailing & Transfers'),'car'],
  maps_navigation:[text('地图与导航','Maps & Navigation'),'map'],
  food_discovery:[text('餐厅发现与评价','Food Discovery & Reviews'),'utensils'],
  food_delivery:[text('当地外卖','Food Delivery'),'bag'],
  intercity_booking:[text('城际票务与渡轮聚合','Intercity & Ferry Booking'),'ticket'],
  urban_transit:[text('城市轨道与公共交通','Urban Transit'),'train'],
  translation:[text('语言翻译与识图','Translation & OCR'),'translate'],
  communication:[text('当地通信与社交','Local Communication'),'chat'],
  official_tourism:[text('官方旅游服务','Official Tourism Services'),'landmark'],
  safety_emergency:[text('旅游警察及紧急服务','Safety & Emergency'),'shield'],
  activities_booking:[text('活动与体验预订','Activities & Tours'),'compass'],
  accommodation_booking:[text('住宿库存与比价复核','Stay Inventory & Recheck'),'bed'],
  weather_environment:[text('天气与空气质量','Weather & Environment'),'cloud'],
  currency_payment:[text('汇率换算与支付辅助','Currency & Payments'),'wallet']
 };
 const statusMap={verified_active:[text('正常运营','Active'),'status-active'],conditional:[text('条件可用','Conditional'),'status-conditional'],regional:[text('特定地区','Regional'),'status-regional']};
 function card(a){
  const isEn=lang==='en',appName=isEn?(a.name_en||a.name):a.name;
  const catLabel=(categories[a.category]||[a.category])[0];
  const [stText,stClass]=statusMap[a.availability_status]||[a.availability_status,''];
  const uses=(isEn?a.use_cases_en:a.use_cases_cn)||[];
  const limits=(isEn?a.limitations_en:a.limitations_cn)||[];
  const dests=(a.destinations||[]).map(d=>d==='all'?text('全国通用','Nationwide'):translated(d)).join(' · ');
  const isServiceOnly=['safety_emergency','official_tourism'].includes(a.category)||(!a.ios_url&&!a.android_url);
  let mainBtn='';
  if(isServiceOnly){
    const pUrl=a.official_url||(a.phone_url?('tel:'+a.phone_url):'#');
    const pLabel=a.phone_url?text('一键拨号 ✆','Call Direct ✆'):text('官方直达 ↗','Official Web ↗');
    mainBtn='<a href="'+esc(pUrl)+'" target="_blank" rel="noopener noreferrer" class="app-main-btn">'+pLabel+'</a>';
  }else{
    const storeBtns=[];
    if(a.ios_url)storeBtns.push('<a href="'+esc(a.ios_url)+'" target="_blank" rel="noopener noreferrer" class="app-store-pill">App Store ↗</a>');
    if(a.android_url)storeBtns.push('<a href="'+esc(a.android_url)+'" target="_blank" rel="noopener noreferrer" class="app-store-pill">Google Play ↗</a>');
    if(!storeBtns.length&&a.official_url)storeBtns.push('<a href="'+esc(a.official_url)+'" target="_blank" rel="noopener noreferrer" class="app-store-pill">'+text('官网直达 ↗','Official ↗')+'</a>');
    mainBtn='<div class="app-store-group">'+storeBtns.join('')+'</div>';
  }
  const extraLinks=[];
  if(a.official_url&&a.ios_url)extraLinks.push('<a href="'+esc(a.ios_url)+'" target="_blank" rel="noopener noreferrer">App Store ↗</a>');
  if(a.official_url&&a.android_url)extraLinks.push('<a href="'+esc(a.android_url)+'" target="_blank" rel="noopener noreferrer">Google Play ↗</a>');
  const warn=limits.length?'<div class="app-limitations"><small>'+text('使用限制 / 注意事项','Key Limitations & Notes')+'</small><p>'+limits.map(esc).join('<br>')+'</p></div>':'';
  const pay=a.payment_notes_cn?'<div class="app-subnote"><small>'+text('支付说明','Payment Note')+'</small><span>'+esc(isEn?(a.payment_notes_en||a.payment_notes_cn):a.payment_notes_cn)+'</span></div>':'';
  const useSummary=uses.slice(0,3).join(' · ');
  return '<article class="app-card" data-priority="'+esc(a.priority)+'" data-status="'+esc(a.availability_status)+'"><div class="app-card-summary"><div class="app-card-lead"><div class="app-card-tags"><span class="app-category-tag">'+esc(catLabel)+'</span><span class="app-status-badge '+esc(stClass)+'">'+esc(stText)+'</span></div><h4>'+esc(appName)+'</h4><p class="app-brief-use">'+esc(useSummary)+'</p></div><div class="app-card-action">'+mainBtn+'</div></div><details class="app-card-details"><summary><span>'+text('详细信息 (适用范围、限制与备用入口)','Details (Scope, Limitations & Stores)')+'</span><span class="app-details-arrow" aria-hidden="true">+</span></summary><div class="app-details-body"><p class="app-scope"><small>'+text('适用范围','Scope')+': </small><b>'+esc(dests)+'</b></p>'+warn+pay+(extraLinks.length?'<div class="app-extra-links">'+extraLinks.join(' · ')+'</div>':'')+'<div class="app-footer"><small>'+text('核验日期','Verified')+': '+esc(a.verified_at||'')+'</small></div></div></details></article>';
 }
 const essential=active.filter(a=>a.priority==='essential'),other=active.filter(a=>a.priority!=='essential');
 let res='';
 if(essential.length){
  res+='<section class="app-section app-essential-section"><div class="app-section-head"><h4>'+text('出发前建议装好 (核心工具)','Essential Apps (Install Before Departure)')+'</h4><p>'+text('影响在途交通、沟通联络与安全的核心工具，建议出行前完成注册与网络配置。','Core mobility, transit, communication and emergency apps essential for smooth arrival.')+'</p></div><div class="app-lead">'+essential.map(card).join('')+'</div></section>';
 }
 if(other.length){
  const groups=[
   {cn:'在地出行与公共交通',en:'Local Mobility & Transit',cats:['ride_hailing','maps_navigation','urban_transit']},
   {cn:'本地餐饮与外卖',en:'Dining & Food Delivery',cats:['food_discovery','food_delivery']},
   {cn:'城际交通与票务代订',en:'Intercity Travel & Bookings',cats:['intercity_booking','activities_booking','accommodation_booking']},
   {cn:'通信、翻译与实用工具',en:'Communication, Translation & Utilities',cats:['communication','translation','currency_payment','weather_environment']},
   {cn:'官方旅游与应急求助',en:'Official Tourism & Emergency',cats:['official_tourism','safety_emergency']}
  ];
  res+='<section class="app-section app-drawer-section"><div class="app-section-head"><h4>'+text('按需安装与场景工具','On-Demand & Specialized Utilities')+'</h4><p>'+text('按目的地与具体需求选装，各卡片包含适用范围与使用限制说明。','Optional utilities categorized by use-case with explicit coverage and restriction notes.')+'</p></div><div class="app-drawers">';
  groups.forEach((grp,idx)=>{
   const grpApps=other.filter(a=>grp.cats.includes(a.category));
   if(!grpApps.length)return;
   res+='<details class="app-drawer" '+(idx===0?'open':'')+'><summary><span class="app-drawer-title"><small>'+text('工具场景','Category')+'</small><b>'+esc(text(grp.cn,grp.en))+'</b><em>'+grpApps.length+text(' 款工具',' apps')+'</em></span><span class="branch-toggle" aria-hidden="true">+</span></summary><div class="app-grid">'+grpApps.map(card).join('')+'</div></details>';
  });
  res+='</div></section>';
 }
 return res;
}
function sourcesHTML(rows){const groups=new Map();for(const row of rows){const key=row[4]||text('其他来源','Other sources');if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);}return '<div class="source-groups">'+[...groups].map(([kind,items])=>'<details><summary><span><small>'+text('证据类别','Evidence group')+'</small><b>'+esc(translated(kind))+'</b></span><em>'+items.length+text(' 条',' records')+'</em><span class="branch-toggle" aria-hidden="true">+</span></summary><div class="source-rows">'+items.map(row=>'<article><div><small>'+esc(placeLabel(row[1]))+'</small><b>'+esc(lang==='en'?(row[2]||translated(row[2])):row[2])+'</b><p>'+esc(translated(row[6]))+' · '+esc(translated(row[8]))+'</p></div><a href="'+esc(row[3])+'" target="_blank" rel="noopener noreferrer">'+text('查看来源','Open source')+' ↗</a></article>').join('')+'</div></details>').join('')+'</div>';}
function moduleHTML(key){
 const spec=config.modules[key],rows=current()[key]||[];
 const grouped=['hotels','restaurants','cafes','attractions','dive_sites'].includes(key);
 let body=key==='routes'?routeHTML(rows):key==='itinerary'?days(rows):key==='editorial_media'?editorial(rows):key==='local_apps'?localAppsHTML(current().local_apps||[]):grouped?poiBranches(rows,spec,key):key==='local_chains'?appShortcuts(['food_discovery','food_delivery'],text('外卖与探店','Food & delivery'),'food')+leadCards(rows):key==='worth_it'?highlights(rows):key==='transport'?appShortcuts(['ride_hailing','urban_transit','intercity_booking'],text('交通与票务','Transport & booking'),'transport')+transportHTML(rows):key==='transport_nodes'?nodeBranches(rows):key==='local_knowledge'?appShortcuts(['safety_emergency','communication'],text('通信与求助','Safety & telecom'),'notes')+localKnowledgeHTML(rows):['practical','packing'].includes(key)?tipBranches(rows,key):key==='budget'?budgetHTML(rows):key==='source_evidence'?sourcesHTML(rows):rows.map(row=>'image'in spec?poi(row,spec):'<article class="record"><b>'+linked(fields(row)[0]??'')+'</b><p>'+fields(row).slice(1).map(linked).join(' · ')+'</p></article>').join('');
 const wide=grouped||['local_chains','worth_it','transport','transport_nodes','local_knowledge','practical','packing','budget','local_apps','source_evidence'].includes(key);
 return '<section class="module'+(wide?' module-wide':'')+'" data-module="'+key+'"><div class="module-heading"><h3>'+esc(spec[lang])+'</h3><span>'+rows.length+'</span></div>'+(body||'<p class="empty">'+text('暂无已核验数据；未用演示内容填充。','No verified records; no filler added.')+'</p>')+'</section>';
}
function renderPanel(){
 const active=config.tabs.find(t=>t.id===tab);$('panel-title').textContent=active[lang];
 $('panel-count').textContent=active.modules.reduce((n,k)=>n+(current()[k]||[]).length,0)+text(' 条记录',' records');
 $('panel-body').innerHTML=active.modules.filter(key=>key!=='editorial_media').map(moduleHTML).join('');
 $('content').setAttribute('aria-labelledby','tab-'+tab);
 document.querySelectorAll('[role=tab]').forEach(b=>{const selected=b.dataset.tab===tab;b.setAttribute('aria-selected',selected);b.tabIndex=selected?0:-1;});
 $('content').scrollTop=0;
 positionIndicator();
 prepareReveals();
}
let revealObserver;
function prepareReveals(){
 if(revealObserver)revealObserver.disconnect();
 const nodes=[...document.querySelectorAll('.module-heading,.route-feature,.day,.poi,.record,.editorial-inline,.tips-lead article,.tip-branches details,.budget-overview')];
 if(reducedMotion()||!('IntersectionObserver'in window)){nodes.forEach(node=>node.classList.add('is-revealed'));return;}
 revealObserver=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add('is-revealed');revealObserver.unobserve(entry.target);}}),{rootMargin:'0px 0px -8% 0px',threshold:.08});
 nodes.forEach((node,index)=>{node.classList.add('reveal-pending');node.style.setProperty('--reveal-delay',Math.min(index%4,3)*45+'ms');revealObserver.observe(node);});
}
function positionIndicator(){
 const selected=$('tabs').querySelector('[role=tab][aria-selected=true]'),indicator=$('tab-indicator');
 if(!selected||!indicator)return;
 indicator.style.width=selected.offsetWidth+'px';indicator.style.transform='translateX('+selected.offsetLeft+'px)';
 requestAnimationFrame(()=>indicator.classList.add('is-ready'));
}
function activateTab(next){
 if(!config.tabs.some(item=>item.id===next)||next===tab)return;
 const tabBtn=$('tab-'+next);if(tabBtn)try{tabBtn.scrollIntoView({behavior:reducedMotion()?'auto':'smooth',inline:'center',block:'nearest'});}catch(e){}
 const panel=$('content'),serial=++transitionSerial;
 if(reducedMotion()){tab=next;renderPanel();const targetTop=panel.getBoundingClientRect().top+scrollY-92;scrollTo({top:Math.max(0,targetTop),behavior:'auto'});return;}
 panel.classList.remove('is-entering');panel.classList.add('is-leaving');panel.setAttribute('aria-busy','true');
 setTimeout(()=>{if(serial!==transitionSerial)return;tab=next;renderPanel();panel.classList.remove('is-leaving');panel.classList.add('is-entering');const targetTop=panel.getBoundingClientRect().top+scrollY-92;scrollTo({top:Math.max(0,targetTop),behavior:reducedMotion()?'auto':'smooth'});requestAnimationFrame(()=>requestAnimationFrame(()=>panel.classList.remove('is-entering')));setTimeout(()=>{if(serial===transitionSerial)panel.removeAttribute('aria-busy');},220);},120);
}
function activateRoute(next){
 if(!next||next===route)return;
 const body=$('panel-body'),serial=++transitionSerial;
 if(reducedMotion()){route=next;renderPanel();renderHeroCarousel(true);return;}
 body.classList.remove('route-entering');body.classList.add('route-leaving');body.setAttribute('aria-busy','true');
 setTimeout(()=>{if(serial!==transitionSerial)return;route=next;renderPanel();renderHeroCarousel(true);body.classList.remove('route-leaving');body.classList.add('route-entering');requestAnimationFrame(()=>requestAnimationFrame(()=>body.classList.remove('route-entering')));setTimeout(()=>{if(serial===transitionSerial)body.removeAttribute('aria-busy');},260);},130);
}
function setLanguage(next){
 lang=next;document.documentElement.lang=lang==='cn'?'zh-CN':'en';
 $('tabs').innerHTML=config.tabs.map(t=>'<button id="tab-'+t.id+'" type="button" role="tab" aria-controls="content" data-tab="'+t.id+'">'+esc(t[lang])+'</button>').join('')+'<span id="tab-indicator" aria-hidden="true"></span>';
 $('language').textContent=text('English','中文');$('language').hidden=Object.keys(payload.editions).length<2;
 $('language').setAttribute('aria-label',text('切换到英文','Switch to Chinese'));
 const c=current(),country=lang==='en'?(c.country_en||c.country):c.country;
 const primaryRoute=(c.routes||[])[0]||[];
 const durationStr=String(primaryRoute[3]||'');
 const daysMatch=durationStr.match(/\d+/);
 const daysCount=daysMatch?daysMatch[0]:(c.duration_days||(c.itinerary||[]).length||'');
 const routeName=lang==='en'?(primaryRoute[1]||primaryRoute[0]||''):(primaryRoute[0]||'');
 const routeType=c.theme==='ocean'?text('海岛路线','Island Route'):text('旅行路线','Travel Route');
 const titleLine=lang==='cn'
  ?(daysCount?`${daysCount}天${routeType}`:routeType)+(routeName?` · ${routeName}`:'')
  :(daysCount?`${daysCount}-Day ${routeType}`:routeType)+(routeName?` · ${routeName}`:'');
 const evidenceDates=(c.source_evidence||[]).map(row=>String(row[5]||'')).filter(value=>/^\d{4}-\d{2}-\d{2}$/.test(value)).sort(),latestDate=evidenceDates.at(-1)||'';
 $('eyebrow').textContent='Travel-Scope / '+(c.theme_label||'Travel Guide');
 $('headline').innerHTML=esc(country)+'<br><span class="highlight">'+esc(titleLine)+'</span>';
 $('summary').textContent=text('包含路线、每日行程、住宿、美食、景点、交通、预算与行前信息。','Routes, daily plans, stays, food, sights, transport, budget and practical information in one guide.');
 $('media-caption').textContent=lang==='en'?(c.hero_credit_en||'Editorial photograph'):(c.hero_credit_cn||'编辑摄影');
 $('status').textContent=c.demo_mode?text('界面演示 · 非旅行建议','Interface demo · not travel advice'):(latestDate?text('更新于 '+latestDate+' · 动态信息请临行复核','Updated '+latestDate+' · Recheck dynamic information before travel'):text('动态信息请临行复核','Recheck dynamic information before travel'));
 renderPanel();renderHeroCarousel(true);
}
function changeLanguage(){
 if(Object.keys(payload.editions).length<2)return;
 const next=lang==='cn'?'en':'cn',surfaces=[$('intro'),$('content')].filter(Boolean),serial=++transitionSerial;
 if(reducedMotion()){setLanguage(next);return;}
 surfaces.forEach(node=>{node.classList.remove('language-enter');node.classList.add('language-leave');});
 setTimeout(()=>{if(serial!==transitionSerial)return;setLanguage(next);surfaces.forEach(node=>{node.classList.remove('language-leave');node.classList.add('language-enter');});requestAnimationFrame(()=>requestAnimationFrame(()=>surfaces.forEach(node=>node.classList.remove('language-enter'))));},120);
}
let heroIndex=0,heroTimer=0,heroItems=[];
function selectedHeroItems(){
 const c=current(),routes=c.routes||[],active=routes.find(row=>row[0]===route)||routes[0],corridor=String(active?.[2]||''),all=(c.editorial_media||[]).filter(item=>item.image),routed=all.filter(item=>item.route===route),matched=all.filter(item=>corridor.includes(item.destination));
 const maxHero=config?.presentation?.hero_carousel?.max_route_images||3;
 const chosen=[],destinations=new Set(),images=new Set();
 function addCandidates(list){
  for(const item of list){if(chosen.length>=maxHero)break;if(!destinations.has(item.destination)&&!images.has(item.image)){chosen.push(item);destinations.add(item.destination);images.add(item.image);}}
  for(const item of list){if(chosen.length>=maxHero)break;if(!images.has(item.image)){chosen.push(item);images.add(item.image);}}
 }
 addCandidates(routed);
 if(chosen.length<maxHero)addCandidates(matched);
 if(chosen.length<maxHero)addCandidates(all);
 if(!chosen.length&&c.hero_image)chosen.push({image:c.hero_image,title:text('目的地影像','Destination image'),title_en:'Destination image',credit_cn:c.hero_credit_cn||'',credit_en:c.hero_credit_en||''});
 return chosen;
}
function applyThemePalette(){
 const c=current(),p=c.palette||(c.theme==='ocean'?{deep:'#0B2239',primary:'#183C55',accent:'#3F83A3',warm_accent:'#C8B28E',ivory:'#F4F0E8',card_bg:'#FCFBF8'}:null);
 if(p){
  const root=document.documentElement.style;
  if(p.deep)root.setProperty('--deep',p.deep);
  if(p.primary)root.setProperty('--primary',p.primary);
  if(p.accent)root.setProperty('--accent',p.accent);
  if(p.warm_accent)root.setProperty('--warm-accent',p.warm_accent);
  if(p.ivory)root.setProperty('--paper-warm',p.ivory);
  if(p.card_bg)root.setProperty('--paper',p.card_bg);
 }
}
function heroCredit(item){const explicit=lang==='en'?item.credit_en:item.credit_cn;if(explicit)return explicit;const title=lang==='en'?(item.title_en||item.title):item.title;return [title,item.author,item.license].filter(Boolean).join(' · ');}
function showHero(index,restart=false){
 if(!heroItems.length)return;heroIndex=(index+heroItems.length)%heroItems.length;
 document.querySelectorAll('.hero-slide').forEach((node,i)=>node.classList.toggle('is-active',i===heroIndex));
 document.querySelectorAll('.hero-dot').forEach((node,i)=>node.setAttribute('aria-current',i===heroIndex?'true':'false'));
 $('media-caption').textContent=heroCredit(heroItems[heroIndex]);
 if(restart)startHeroTimer();
}
function startHeroTimer(){clearInterval(heroTimer);if(reducedMotion()||heroItems.length<2)return;heroTimer=setInterval(()=>showHero(heroIndex+1),5000);}
function renderHeroCarousel(reset=false){
 applyThemePalette();
 heroItems=selectedHeroItems();if(reset)heroIndex=0;
 const card=document.querySelector('.media-card');card.classList.toggle('has-carousel',heroItems.length>1);
 $('hero-media').innerHTML=heroItems.map((item,index)=>'<div class="hero-slide'+(index===heroIndex?' is-active':'')+'"><img src="'+esc(item.image)+'" alt="'+esc(lang==='en'?(item.title_en||item.title):item.title)+'" '+(index?'loading="lazy"':'')+'></div>').join('')+(heroItems.length>1?'<div class="hero-dots" role="group" data-interval="5000" aria-label="'+text('图片轮播','Image carousel')+'">'+heroItems.map((_,index)=>'<button class="hero-dot" type="button" data-hero-index="'+index+'" aria-label="'+text('查看图片 ','Show image ')+(index+1)+'" aria-current="'+(index===heroIndex)+'"></button>').join('')+'</div>':'');
 document.documentElement.style.setProperty('--hero-image','url('+JSON.stringify(heroItems[0]?.image||current().hero_image||'')+')');
 showHero(heroIndex);startHeroTimer();
}
$('hero-media').onclick=e=>{const dot=e.target.closest('[data-hero-index]');if(dot)showHero(Number(dot.dataset.heroIndex),true);};
const mediaCard=document.querySelector('.media-card');
mediaCard.addEventListener('mouseenter',()=>{if(!reducedMotion())clearInterval(heroTimer);});
mediaCard.addEventListener('mouseleave',()=>startHeroTimer());
document.addEventListener('visibilitychange',()=>document.hidden?clearInterval(heroTimer):startHeroTimer());
document.addEventListener('error',event=>{if(event.target.tagName==='IMG'){const img=event.target;img.hidden=true;const note=document.createElement('span');note.className='image-missing';note.textContent=text('图片未加载','Image unavailable');img.after(note);$('media-status').textContent=text('存在未加载图片','Some images are unavailable');}},true);
$('tabs').onclick=e=>{const b=e.target.closest('[data-tab]');if(b)activateTab(b.dataset.tab);};
$('panel-body').onclick=e=>{const b=e.target.closest('[data-route]');if(b)activateRoute(b.dataset.route);};
$('tabs').onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();let i=config.tabs.findIndex(t=>t.id===tab);i=e.key==='Home'?0:e.key==='End'?config.tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+config.tabs.length)%config.tabs.length;const next=config.tabs[i].id;$('tab-'+next).focus();activateTab(next);};
$('language').onclick=changeLanguage;
addEventListener('resize',positionIndicator,{passive:true});
const navigation=document.querySelector('.navigation');
let navFrame=0,navDocked=false;
function updateFloatingNavigation(){
 navFrame=0;
 const docked=Math.max(0,scrollY)>180;
 if(docked!==navDocked){navDocked=docked;navigation.classList.toggle('is-docked',docked);requestAnimationFrame(positionIndicator);}
 navigation.classList.toggle('is-visible',docked);
}
addEventListener('scroll',()=>{if(!navFrame)navFrame=requestAnimationFrame(updateFloatingNavigation);},{passive:true});
updateFloatingNavigation();
setLanguage(lang);
})();
