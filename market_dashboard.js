"use strict";

const $ = id => document.getElementById(id);
const num = new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const format = value => value == null || value === "" || !Number.isFinite(Number(value)) ? "—" : num.format(value);
const fxNumber = new Intl.NumberFormat("zh-CN", {minimumFractionDigits:4,maximumFractionDigits:4});
const formatValue = (value,unit) => /^(CNY|CNH)\/USD$/.test(unit || "") && Number.isFinite(value) ? fxNumber.format(value) : format(value);
const percent = value => format(value) === "—" ? "—" : (Number(value) > 0 ? "+" : "") + format(value) + "%";
function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function change(value) {
  return node("span", percent(value), value == null ? "" : value >= 0 ? "positive" : "negative");
}
function closeChange(value) {
  const label = change(value);
  label.textContent = "较昨收 " + label.textContent;
  return label;
}

const instrumentLogos = {
  usAAPL: "usAAPL.png",
  usAMZN: "usAMZN.png",
  usMSFT: "usMSFT.png",
  usNVDA: "usNVDA.png",
  sh601318: "sh601318.png",
};

function instrumentCard(id, name, quote, selected, select, accent = "#d6b479") {
  const button = node("button", null, "instrument-card");
  button.type = "button";
  button.dataset.ticker = id;
  button.setAttribute("aria-pressed", selected);
  button.style.setProperty("--instrument-accent", accent);
  button.title = [name, quote?.code, quote?.timestamp ? formatTime(quote) : ""].filter(Boolean).join(" · ");
  const badge = node("span", null, "instrument-logo");
  badge.setAttribute("aria-hidden","true");
  const shortName = name.replace(/^(中证|800)/,"");
  badge.textContent = /^[a-z0-9]/i.test(shortName)
    ? (quote?.code || shortName).split(".")[0].slice(0,4).toUpperCase()
    : Array.from(shortName || name).slice(0,2).join("");
  const logo = instrumentLogos[id];
  if (logo) {
    const img = node("img");
    img.alt = "";
    img.decoding = "async";
    img.addEventListener("load", () => badge.replaceChildren(img), {once:true});
    img.src = "assets/market-logos/" + logo;
  }
  const price = node("span", formatValue(quote?.value,quote?.unit), "instrument-price");
  if (quote?.value != null && quote.unit) {
    const unit = quote.unit === "CNY" ? "元" : quote.unit;
    price.append(node("small", unit));
  }
  button.append(badge, node("span", name, "instrument-name"), price);
  button.addEventListener("click", select);
  return button;
}

function replaceInstrumentCards(grid, items) {
  const focus = grid.contains(document.activeElement) ? document.activeElement.dataset.ticker : null;
  grid.replaceChildren(...items);
  if (focus) items.find(item => item.dataset.ticker === focus)?.focus({preventScroll:true});
}

async function api(path) {
  const response = await fetch("/api/" + path, {cache: "no-store"});
  const result = await response.json();
  if (!response.ok) throw Error(result.error || "请求失败");
  return result;
}
function shiftDate(day, offset) {
  return new Date(Date.parse(day+"T00:00:00Z")+offset*86400000).toISOString().slice(0,10);
}

function dateOffset(day, origin) {
  return Math.round((Date.parse(day)-Date.parse(origin))/86400000);
}

class ChartTimeline {
  constructor(mount,onChange) {
    this.days=7;
    this.callback=onChange;
    this.root=$("timeline-template").content.firstElementChild.cloneNode(true);
    mount.append(this.root);
    this.start=this.root.querySelector(".timeline-start");
    this.end=this.root.querySelector(".timeline-end");
    this.slider=this.root.querySelector("input[type=range]");
    this.lookback=this.root.querySelector(".timeline-lookback");
    this.presets=[[7,"近 7 天"],[30,"近 1 月"],[90,"近 3 月"],[180,"近 6 月"],[365,"近 1 年"]].map(([days,label])=>{
      const button=node("button",label);
      button.type="button";
      button.dataset.days=days;
      button.setAttribute("aria-pressed",days===7);
      button.addEventListener("click",()=>this.setLookback(days));
      return button;
    });
    this.root.querySelector(".timeline-presets").replaceChildren(...this.presets);
    this.slider.addEventListener("input",()=>this.setLookback(Number(this.slider.value)));
    [this.start,this.end].forEach(field=>field.addEventListener("change",()=>{
      if (!this.latest || !this.start.value || !this.end.value) return;
      this.custom={start:this.start.value,end:this.end.value};
      this.changed();
    }));
  }
  setLookback(days) {
    this.days=days;
    this.custom=null;
    this.changed();
  }
  changed() {
    if (this.latest) this.setLatest(this.latest);
    cancelAnimationFrame(this.pending);
    this.pending=requestAnimationFrame(this.callback);
  }
  setLatest(latest) {
    this.latest=latest;
    const floor=shiftDate(latest,-365);
    const cap=(value,max)=>value<floor ? floor : value>max ? max : value;
    const end=this.custom ? cap(this.custom.end,latest) : latest;
    const start=this.custom ? cap(this.custom.start,end) : shiftDate(latest,-this.days);
    this.start.min=floor;
    this.start.max=end;
    this.end.min=floor;
    this.end.max=latest;
    this.start.value=start;
    this.end.value=end;
    this.slider.value=this.custom ? Math.max(1,dateOffset(start,latest)*-1) : this.days;
    const lookback=this.slider.value+" 天";
    this.lookback.textContent=this.custom ? "自定义" : lookback;
    this.slider.setAttribute("aria-valuetext",lookback+"，拖动后结束日固定为 "+latest);
    this.presets.forEach(button=>button.setAttribute("aria-pressed",!this.custom && Number(button.dataset.days)===this.days));
    this.bounds={start,end};
    return this.bounds;
  }
}

function calendarAxis({start,end},left,right){
  const span=dateOffset(end,start);
  return {
    dates:Array.from({length:span+1},(_,day)=>shiftDate(start,day)),
    x: date=>span ? left+dateOffset(date,start)*(right-left)/span : (left+right)/2
  };
}

function matchesInstrument(name,id,query){
  return (name+" "+id+" "+(lookup.get(id)?.code || "")).toLowerCase().includes(query.trim().toLowerCase());
}

const macroRate = {id:"DGS10", name:"美国 10 年期国债收益率", code:"DGS10", unit:"%", source:"FRED"};
const externalMarkets={
  "大宗商品":[["101.GC00Y","COMEX 黄金期货","美元/盎司"],["101.SI00Y","COMEX 白银期货","美元/盎司"],
    ["102.CL00Y","WTI 原油期货","美元/桶"],["101.HG00Y","COMEX 铜期货","美元/磅"]],
  "外汇市场":[["100.UDI","美元指数","点"],["133.USDCNH","美元兑离岸人民币","CNH/USD"],["USDCNY","美元兑在岸人民币","CNY/USD"]]
};
const featuredBoards=[
  {id:"BK1617",name:"黄金",code:"BK1617",unit:"点"},
  {id:"BK1340",name:"印制电路板",code:"BK1340",unit:"点"}
];
const electronics={id:"BK0459",name:"电子元件",code:"BK0459",unit:"点"};

function uniqueInstruments(rows){
  return Array.from(new Map(rows.map(item=>[item.id,item])).values());
}
function marketGroupRows(name,boardRows=industryRows){
  if (name==="宏观利率") return [lookup.get(macroRate.id) || macroRate];
  if (name==="中国行业") return uniqueInstruments([...featuredBoards,...boardRows]);
  if (externalMarkets[name]) return externalMarkets[name].map(([id,label,unit])=>lookup.get(id)||{id,name:label,code:id.split(".").at(-1),unit});
  const rows=snapshots?.groups[name] || [];
  if(name==="中证 800 行业") return [...rows,electronics];
  return rows;
}

async function loadInstrumentQuote(item, refresh=false){
  if(lookup.has(item.id) && !refresh) return lookup.get(item.id);
  const quote=await api("quote?symbol="+encodeURIComponent(item.id));
  lookup.set(item.id,quote);
  return quote;
}

async function refreshExternalQuotes(market){
  await Promise.allSettled(marketGroupRows(market).map(item=>loadInstrumentQuote(item,true)));
  if(group===market){renderQuotes();renderQuoteDetail();}
  window.dispatchEvent(new Event("market-quotes"));
}

const lookup = new Map();
let snapshots = null;
let group = "中证 800 行业", industryPage = 1, industryRows = [], industryTotal = 0;
let active = "sh000300";
let extraTimeline, extraResult, extraGeometry, extraMatches=[];
let series = [], trendRequest = 0, boardRequest = 0;
let factorData = null, factorMode = "published", showFactorMetrics = false;
let refreshPending = false;

function press(container, button) {
  $(container).querySelectorAll("button").forEach(item => item.setAttribute("aria-pressed", item === button));
}
function formatTime(row) {
  return [row.timestamp, row.zone, row.source].filter(Boolean).join(" · ");
}
function renderCards() {
  const cards = ["sh000001", "sh000300", "us.INX", "us.IXIC"].map(id => {
    const item = lookup.get(id);
    const button = node("button", "", "quote-card");
    button.type = "button";
    const defaults = {sh000001:"上证指数",sh000300:"沪深 300", "us.INX":"标普 500 指数", "us.IXIC":"纳斯达克综合指数"};
    button.append(node("span", item?.name || defaults[id]), node("strong", format(item?.value), "quote-price"));
    const bottom = node("span", "", "card-bottom");
    bottom.append(change(item?.percent), node("small", item ? item.timestamp.slice(5, 16) + " " + item.zone : "报价暂不可用"));
    button.append(bottom);
    button.disabled = !item;
    button.addEventListener("click", () => window.dispatchEvent(new CustomEvent("market-index-select", {detail:id})));
    return button;
  });
  $("overview").replaceChildren(...cards);
}
function renderQuotes() {
  const term=$("extra-search").querySelector("input").value;
  const rows=uniqueInstruments([...marketGroupRows(group).filter(item=>matchesInstrument(item.name,item.id,term)),...extraMatches]);
  const items=rows.map(row=>lookup.get(row.id)||row);
  $("quote-count").textContent = group === "中国行业" && industryTotal ? industryTotal + " 个板块" : rows.length + " 个标的";
  $("industry-pages").hidden = group !== "中国行业" || !industryTotal;
  const pages = Math.max(1, Math.ceil(industryTotal / 100));
  $("industry-page").textContent = industryPage + " / " + pages;
  $("prev").disabled = industryPage <= 1;
  $("next").disabled = industryPage >= pages;
  const cards = items.map(item => instrumentCard(item.id, item.name, item, item.id === active,
    () => selectSymbol(item.id, item.name)));
  if (!cards.length) cards.push(node("p", term ? "暂无匹配标的" : "暂未取得行情", "note instrument-empty"));
  replaceInstrumentCards($("quotes"), cards);
}
function renderQuoteDetail() {
  const item = lookup.get(active);
  $("selected-quote").hidden = !item;
  $("selected-price").textContent = item ? [formatValue(item.value,item.unit), item.unit].join(" ") : "";
  $("selected-change").replaceChildren(...(item?.percent == null ? [] : [closeChange(item.percent)]));
  $("selected-time").textContent = item ? formatTime(item) : "";
}
async function boardPage(number) {
  const ticket = ++boardRequest;
  $("quote-note").textContent = "正在读取行业板块…";
  try {
    const result = await api("industries?page=" + number);
    if (ticket !== boardRequest) return;
    if (group !== "中国行业") return;
    industryRows = result.rows;
    industryTotal = result.total;
    industryPage = result.page;
    result.rows.forEach(item => lookup.set(item.id,item));
    renderQuotes();
    $("quote-note").textContent = "东方财富行业板块 · 按涨跌幅排序" + (result.cached ? " · 上次保存" : "");
  } catch (error) {
    if (ticket === boardRequest) $("quote-note").textContent = "东方财富细分板块暂不可用，可切换至 A 股行业。";
  }
}
async function refresh() {
  if (refreshPending) return;
  refreshPending = true;
  $("refresh").disabled = true;
  try {
    const result = await api("overview");
    snapshots = Object.keys(result.groups).length ? result : snapshots || result;
    Object.values(result.groups).flat().forEach(item => lookup.set(item.id, item));
    renderCards();
    window.dispatchEvent(new Event("market-quotes"));
    if (group === "中国行业") boardPage(industryPage);
    else if(externalMarkets[group]) refreshExternalQuotes(group);
    else renderQuotes();
    renderQuoteDetail();
    const failed = Object.keys(result.failures);
    const time = result.fetchedAt.slice(11,19);
    $("quote-status").textContent = failed.length
      ? time + " 查询 · " + failed.join("、") + "暂不可用，已加载报价保留原时间"
      : time + " 查询 · 每 30 秒刷新";
  } catch (error) {
    $("quote-status").textContent = "行情连接暂不可用，已加载报价保留原时间";
  } finally {
    refreshPending = false;
    $("refresh").disabled = false;
  }
}

function renderIndicators(points) {
  if (active === "DGS10" || points.length < 2) {
    if(active === "DGS10" && points.length >= 2){
      const value=points.at(-1).value;
      const rows=[
        ["最新收益率",format(value)+"%"],
        ["区间变化",format(value-points[0].value)+" 个百分点"],
        ["区间最高",format(Math.max(...points.map(p=>p.value)))+"%"],
        ["区间最低",format(Math.min(...points.map(p=>p.value)))+"%"]
      ];
      $("indicators").replaceChildren(...rows.map(([label,metric])=>{
        const item=node("div");
        item.append(node("dt",label),node("dd",metric));
        return item;
      }));
    } else $("indicators").replaceChildren();
    return;
  }
  const last = points.at(-1).value;
  const momentum = days => points.length > days && points.at(-days-1).value > 0
    ? percent(100 * (last / points.at(-days-1).value - 1)) : "—";
  const trailing = points.slice(-21);
  const returns = trailing.slice(1).map((p, i) => p.value / trailing[i].value - 1);
  const average = returns.reduce((sum, value) => sum + value, 0) / returns.length;
  const volatility = returns.length === 20 ?
    format(Math.sqrt(returns.reduce((sum, value) => sum + (value-average)**2, 0)/20 * 250) * 100) + "%" : "—";
  const volumes = points.slice(-21,-1).map(p => p.volume);
  const validVolumes = volumes.length === 20 && volumes.every(v => v != null && v >= 0);
  const total = validVolumes ? volumes.reduce((sum,v) => sum + v, 0) : 0;
  const ratio = total > 0 && points.at(-1).volume > 0 ? format(points.at(-1).volume / (total / 20)) + "×" : "—";
  const fields = [["5 日动量",momentum(5)],["20 日动量",momentum(20)],["20 日年化波动",volatility],["20 日量比",ratio]];
  $("indicators").replaceChildren(...fields.map(([name, value]) => {
    const item = node("div");
    item.append(node("dt",name), node("dd",value));
    return item;
  }));
}
function drawDateTicks(ctx, dates, left, right, top, bottom, labelY) {
  const count = Math.min(dates.length, Math.max(3, Math.min(9, Math.floor((right-left)/65)+1)));
  ctx.fillStyle = "#bdc8c0";
  ctx.strokeStyle = "#bdd3bf16";
  ctx.lineWidth = 1;
  ctx.textBaseline = "middle";
  for (let i=0; i<count; i++) {
    const index = Math.round(i*(dates.length-1)/Math.max(1,count-1));
    const x = dates.length===1 ? (left+right)/2 : left+index*(right-left)/(dates.length-1);
    ctx.beginPath(); ctx.moveTo(x,top); ctx.lineTo(x,bottom); ctx.stroke();
    ctx.textAlign = i === 0 ? "left" : i === count-1 ? "right" : "center";
    ctx.fillText(dates[index].slice(5),x,labelY);
  }
}

function draw() {
  const canvas = $("trend");
  const ctx = canvas.getContext("2d");
  const {width:w,height:h} = canvas.getBoundingClientRect();
  if (!w || !h) return;
  const scale = window.devicePixelRatio || 1;
  canvas.width = w*scale;
  canvas.height = h*scale;
  ctx.scale(scale,scale);
  extraGeometry=null;
  if (!series.length) return;
  const left=64, right=16, top=15, bottom=32;
  const values = series.map(p => p.value);
  const min=Math.min(...values), max=Math.max(...values);
  const pad=(max-min)*.1 || .1;
  const low=min-pad, high=max+pad;
  const axis=calendarAxis(extraTimeline.bounds,left,w-right);
  const x=i=>axis.x(series[i].date);
  const y=v=>top+(high-v)*(h-top-bottom)/(high-low);
  ctx.font="13px " + getComputedStyle(document.documentElement).getPropertyValue("--dashboard-font");
  ctx.textAlign="right";
  ctx.textBaseline="middle";
  for(let i=0;i<5;i++) {
    const value=low+(high-low)*i/4;
    ctx.strokeStyle="#b1cbb021";ctx.beginPath();ctx.moveTo(left,y(value));ctx.lineTo(w-right,y(value));ctx.stroke();
    ctx.fillStyle="#bcc8bd";ctx.fillText(formatValue(value,lookup.get(active)?.unit),left-7,y(value));
  }
  drawDateTicks(ctx,axis.dates,left,w-right,top,h-bottom,h-13);
  const trace=()=>series.forEach((p,i)=>i?ctx.lineTo(x(i),y(p.value)):ctx.moveTo(x(i),y(p.value)));
  ctx.beginPath();trace();ctx.lineTo(x(series.length-1),h-bottom);ctx.lineTo(x(0),h-bottom);ctx.closePath();
  const fill=ctx.createLinearGradient(0,top,0,h-bottom);
  fill.addColorStop(0,"#d4b57b46");fill.addColorStop(1,"#d4b57b04");ctx.fillStyle=fill;ctx.fill();
  ctx.beginPath();trace();ctx.strokeStyle="#e1c28a";ctx.lineWidth=2;ctx.stroke();
  if(series.length===1){ctx.beginPath();ctx.arc(x(0),y(series[0].value),4,0,Math.PI*2);ctx.fillStyle="#e1c28a";ctx.fill();}
  extraGeometry={x,y};
}
function renderExtraRange(){
  if(!extraResult) return;
  const {points, source, cached}=extraResult;
  const {start,end}=extraTimeline.setLatest(points.at(-1).date);
  series=points.filter(point=>point.date>=start && point.date<=end);
  renderIndicators(points.filter(point=>point.date<=end));
  $("trend-status").textContent=series.length?"":"所选区间没有交易数据";
  $("trend-state").hidden=Boolean(series.length);
  $("trend-source").textContent=[source,cached?"上次保存":"",series.length?series[0].date+" 至 "+series.at(-1).date:""].filter(Boolean).join(" · ");
  draw();
}

async function selectSymbol(symbol, name) {
  const ticket = ++trendRequest;
  active = symbol;
  extraResult=null;
  $("extra-tooltip").hidden=true;
  if (!lookup.has(symbol) && symbol!==macroRate.id) loadInstrumentQuote({id:symbol}).then(()=>{
    if(ticket===trendRequest){renderQuotes();renderQuoteDetail();}
  }).catch(()=>{});
  renderQuotes();
  renderQuoteDetail();
  const title = $("trend-title");
  title.textContent = name;
  if (ticket > 1 && matchMedia("(max-width: 740px)").matches && title.getBoundingClientRect().top >= innerHeight) {
    title.closest("section").scrollIntoView({block:"start"});
  }
  $("trend-subtitle").textContent = symbol === "DGS10" ? "美国财政部序列 · 收益率 %" : symbol + " · 日线";
  $("trend-state").hidden = false;
  $("trend-retry").hidden = true;
  $("trend-official").hidden = true;
  $("trend-status").textContent = "正在加载日线…";
  $("trend").setAttribute("aria-label", name + "日线走势");
  $("trend-source").textContent = "";
  $("valuation").hidden = true;
  $("indicators").replaceChildren();
  series = [];
  draw();
  if (/^(sh|sz)\d{6}$/.test(symbol) && lookup.get(symbol)?.seriesType !== "index" && symbol !== "sh000300") {
    api("valuation?symbol=" + encodeURIComponent(symbol)).then(data => {
      if (ticket !== trendRequest) return;
      const metrics = [
        ["市盈率 · TTM", format(data.pe)], ["市净率", format(data.pb)],
        ["换手率", data.turnover == null ? "—" : format(data.turnover) + "%"],
        ["市值 · 亿元", format(data.marketCapBillions)]
      ];
      $("valuation").replaceChildren(...metrics.map(([label,value]) => {
        const item = node("div");
        item.append(node("dt",label),node("dd",value));
        return item;
      }));
      $("valuation").title = data.source;
      $("valuation").hidden = false;
    }).catch(() => { /* this source is independent of the price history */ });
  }
  try {
    const result = await api(symbol === "DGS10" ? "macro" : "history?symbol=" + encodeURIComponent(symbol)+"&limit=270");
    if (ticket !== trendRequest) return;
    extraResult = result;
    if (symbol === macroRate.id) {
      const last=result.points.at(-1);
      lookup.set(symbol, {...macroRate, value: last.value, timestamp: last.date});
      renderQuoteDetail();
      renderQuotes();
    }
    renderExtraRange();
  } catch (error) {
    if (ticket !== trendRequest) return;
    $("trend-status").textContent = (symbol.startsWith("BK") ? "东方财富板块日线" : "日线") + "暂时无法加载";
    $("trend-retry").hidden = false;
    if (symbol.startsWith("BK")) {
      $("trend-official").href = "https://quote.eastmoney.com/bk/90." + encodeURIComponent(symbol) + ".html";
      $("trend-official").hidden = false;
    }
  }
}
function category(key) {
  key=key.replace(/^SCAN_/,"");
  if(/^(MULTI|BLEND)/.test(key)) return "组合";
  if(/^(DAY|NIGHT|OVERNIGHT)/.test(key)) return "日内与隔夜";
  if(/^VOL/.test(key)) return "波动";
  if(/^(REV|BBREV|RSIREV)/.test(key)) return "反转";
  if(/^MACD/.test(key)) return "技术指标";
  return "动量";
}
function renderFactors() {
  if (!factorData) return;
  const input=$("factor-search").value.trim().toLowerCase(), filter=$("factor-category").value;
  const records=factorData[factorMode];
  $("screening-download").hidden = factorMode !== "screening" || !records.length;
  const rows=records.filter(r => (!filter || category(r.key)===filter) &&
    [r.name,r.key,r.formula].join(" ").toLowerCase().includes(input));
  $("factor-count").textContent = records.length ? "显示 "+rows.length+" / "+records.length+" 条" : "当前数据集没有筛选记录";
  $("factor-rows").replaceChildren(...rows.map(item=>{
    const row=node("tr");
    const heading=node("td"), detail=node("details");
    const summary=node("summary",item.name+(factorMode==="screening"?" · 前 "+Math.round(Number(item.top)*100)+"%":""));
    detail.append(summary,node("p",item.key+" · "+(item.formula || "策略定义见回测看板")));
    if(item.source) detail.append(node("p",item.source));
    if(factorMode==="screening") detail.append(node("p","前半段年化超额 " + percent(item.early_excess) +
     " · 后半段年化超额 "+percent(item.late_excess)));
    heading.append(detail);
    row.append(heading,node("td",category(item.key)));
    for(const field of ["annual_excess","total","mdd"]){
      const cell = node("td");
      if (field !== "annual_excess") {
        cell.className = "extra-metric";
        cell.hidden = !showFactorMetrics;
      }
      cell.append(field==="mdd"?node("span",format(item[field])==="—"?"—":format(item[field])+"%"):change(item[field]));
      row.append(cell);
    }
    return row;
  }));
}

function initExtraSearch(){
  const form=$("extra-search"),input=form.querySelector("input");
  let sequence=0,timer;
  async function search(){
    const q=input.value.trim(),ticket=++sequence;
    if(!q || group!=="中国行业") return;
    try{
      const result=await api("search?market=board&q="+encodeURIComponent(q));
      if(ticket!==sequence || q!==input.value.trim() || group!=="中国行业")return;
      extraMatches=result.rows;
      renderQuotes();
    }catch(_){}
  }
  input.addEventListener("input",()=>{
    sequence++;extraMatches=[];renderQuotes();
    clearTimeout(timer);
    timer=setTimeout(search,280);
  });
  form.addEventListener("submit",event=>{
    event.preventDefault();clearTimeout(timer);search();
  });
}

function initMarketViews(){
  const nav=$("market-view-nav"), links=Array.from(nav.querySelectorAll("a"));
  const show=()=>{
    const historical=location.hash==="#history";
    $("history").hidden=!historical;
    $("intraday").hidden=historical;
    links.forEach(link=>{
      if(link.hash===(historical?"#history":"#intraday")) link.setAttribute("aria-current","page");
      else link.removeAttribute("aria-current");
    });
  };
  nav.addEventListener("click",event=>{
    const link=event.target.closest("a");
    if(!link || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if(location.hash!==link.hash) window.history.pushState(null,"",link.hash);
    show();
    window.scrollTo(0,0);
  });
  window.addEventListener("hashchange",show);
  show();
}

function initMarket() {
  initMarketViews();
  extraTimeline=new ChartTimeline($("extra-timeline"),renderExtraRange);
  initExtraSearch();
  $("groups").addEventListener("click", event=>{
    const button=event.target.closest("[data-group]");
    if(!button) return;
    group=button.dataset.group;
    $("extra-search").querySelector("input").value="";
    extraMatches=[];
    boardRequest++;
    press("groups",button);
    $("quote-note").textContent = group==="中国行业" ? "东方财富行业板块 · 按当日涨跌幅排序" :
      group==="中证 800 行业" ? "中证 800 一级行业指数 · 腾讯财经报价" :
      group==="宏观利率" ? "FRED · 日频观测值" :
      group==="美国行业" ? "美国行业 ETF" : "东方财富行情";
    if(group==="中国行业" && !industryRows.length) boardPage(1);
    if(externalMarkets[group]) refreshExternalQuotes(group);
    const first=marketGroupRows(group)[0];
    if(first && !marketGroupRows(group).some(item=>item.id===active)) selectSymbol(first.id,first.name);
    renderQuotes();
  });
  $("prev").addEventListener("click",()=>boardPage(industryPage-1));
  $("next").addEventListener("click",()=>boardPage(industryPage+1));
  $("trend-retry").addEventListener("click", () => selectSymbol(active, $("trend-title").textContent));
  $("refresh").addEventListener("click", () => {
    refresh();
    window.dispatchEvent(new Event("market-history-refresh"));
  });
  const canvas=$("trend"),tip=$("extra-tooltip");
  canvas.addEventListener("pointerleave",()=>{tip.hidden=true;});
  canvas.addEventListener("pointermove",event=>{
    if(!extraGeometry || !series.length){tip.hidden=true;return;}
    const {x,y}=extraGeometry;
    const index=series.reduce((best,_,i)=>Math.abs(event.offsetX-x(i))<Math.abs(event.offsetX-x(best)) ? i : best,0);
    const point=series[index];
    if(Math.abs(event.offsetX-x(index))>15 || Math.abs(event.offsetY-y(point.value))>17){tip.hidden=true;return;}
    const unit=lookup.get(active)?.unit || (active===macroRate.id?"%":"");
    tip.replaceChildren(node("strong",$("trend-title").textContent),node("span",point.date),
      node("span",formatValue(point.value,unit)+" "+unit));
    tip.hidden=false;
    tip.style.left=Math.max(6,Math.min(event.offsetX+12,canvas.clientWidth-tip.offsetWidth-6))+"px";
    tip.style.top=Math.max(6,Math.min(event.offsetY-12,canvas.clientHeight-tip.offsetHeight-6))+"px";
  });
  new ResizeObserver(draw).observe(canvas);
  renderCards();
  renderQuotes();
  refresh();
  loadInstrumentQuote(electronics).then(()=>{renderQuotes();window.dispatchEvent(new Event("market-quotes"));}).catch(()=>{});
  selectSymbol("sh000928", "中证能源");
  setInterval(()=>{if(!document.hidden)refresh();},30000);
}

function initFactorLibrary() {
  $("factor-mode").addEventListener("click",event=>{
    const button=event.target.closest("[data-mode]");
    if(!button)return;
    factorMode=button.dataset.mode;
    press("factor-mode",button);
    renderFactors();
  });
  $("factor-search").addEventListener("input",renderFactors);
  $("factor-category").addEventListener("change",renderFactors);
  $("factor-metrics").addEventListener("click", event => {
    showFactorMetrics = !showFactorMetrics;
    event.currentTarget.setAttribute("aria-pressed", showFactorMetrics);
    event.currentTarget.textContent = showFactorMetrics ? "隐藏收益明细" : "显示收益明细";
    document.querySelectorAll("th.extra-metric").forEach(cell => cell.hidden = !showFactorMetrics);
    renderFactors();
  });
  api("factors").then(data=>{
    factorData=data;
    $("factor-period").textContent=data.period.join(" 至 ")+" · "+data.source;
    renderFactors();
  }).catch(()=>{$("factor-count").textContent="因子库暂不可用";});
}

if ($("groups")) {
  if (location.hash === "#factor-title") location.replace("factor_library.html#factor-title");
  else initMarket();
} else {
  initFactorLibrary();
}
