"use strict";

const trendBoards = [
  {id:"indices", title:"主要指数", unit:"点", picks:[
    ["sh000001","上证指数"], ["sh000300","沪深 300"], ["sz399001","深证成指"],
    ["us.INX","标普 500"], ["us.IXIC","纳斯达克综合指数"], ["us.DJI","道琼斯工业指数"],
    ["sz399006","创业板指"], ["sh000688","科创 50"]
  ], defaults:["sh000001","sh000300","us.INX","us.IXIC"]},
  {id:"china", title:"沪深 A 股", unit:"CNY", picks:[
    ["sh600519","贵州茅台"], ["sh601318","中国平安"], ["sz300750","宁德时代"],
    ["sz002594","比亚迪"], ["sh600036","招商银行"]
  ], defaults:["sh600519","sz300750","sz002594"], markets:[["sh","沪市"],["sz","深市"]]},
  {id:"usa", title:"美股", unit:"USD", picks:[
    ["usNVDA","英伟达"], ["usAAPL","苹果"], ["usMSFT","微软"], ["usAMZN","亚马逊"],
    ["usGOOGL","谷歌"], ["usMETA","Meta"], ["usTSLA","特斯拉"], ["usSPY","SPY"], ["usQQQ","QQQ"]
  ], defaults:["usNVDA","usAAPL","usMSFT"], markets:[["us","美股"]]}
];
const lineColors = ["#e4bd77","#8cccb1","#88ade5","#e8a0a2","#b8a0e7","#d6d595","#7fcbd0","#d7aa84","#b3bc9b"];
const marketSeries = new Map();

function marketHistory(id) {
  const existing = marketSeries.get(id);
  if (existing) return existing;
  const request = api("history?symbol=" + encodeURIComponent(id) + "&limit=270")
    .catch(error => { if (marketSeries.get(id) === request) marketSeries.delete(id); throw error; });
  marketSeries.set(id, request);
  return request;
}

class MarketBoard {
  constructor(config, container) {
    this.config = config;
    this.picks = new Map(config.picks);
    this.selected = new Set(config.defaults);
    this.single = config.defaults[0];
    this.searchRows = [];
    this.mode = "multi";
    this.ticket = 0;
    this.addTicket = 0;
    this.lines = [];
    this.panel = $("market-board-template").content.firstElementChild.cloneNode(true);
    this.panel.id = config.id + "-market";
    container.insertBefore(this.panel,$("market-extra"));
    const title = this.panel.querySelector("h2");
    title.id = this.panel.id + "-title";
    title.textContent = config.title;
    this.panel.setAttribute("aria-labelledby",title.id);
    this.canvas = this.panel.querySelector("canvas");
    this.canvas.setAttribute("aria-label",config.title+"日线图");
    this.tooltip = this.element(".board-tooltip");
    this.timeline = new ChartTimeline(this.element(".timeline-mount"),()=>this.load());
    this.element(".board-mode").addEventListener("click",event=>{
      const button=event.target.closest("button[data-mode]");
      if(button) this.setMode(button.dataset.mode);
    });
    this.element(".board-retry").addEventListener("click",()=>this.load());
    this.canvas.addEventListener("pointermove",event=>this.hover(event));
    this.canvas.addEventListener("pointerleave",()=>this.clearHover());
    this.canvas.addEventListener("pointerdown",event=>this.hover(event));
    this.enableLookup();
    new ResizeObserver(()=>this.draw()).observe(this.canvas);
    this.renderPicks();
    this.load();
  }

  element(selector) {
    return this.panel.querySelector(selector);
  }

  color(id) {
    return this.selectedColors?.get(id) || lineColors[Array.from(this.picks.keys()).indexOf(id) % lineColors.length];
  }

  updateColors(){
    this.selectedColors=new Map();
    const used=new Set(),keys=Array.from(this.picks.keys());
    for(const id of this.selected){
      const preferred=lineColors[keys.indexOf(id)%lineColors.length];
      const color=used.has(preferred)?lineColors.find(candidate=>!used.has(candidate)) || preferred:preferred;
      used.add(color);
      this.selectedColors.set(id,color);
    }
  }

  setMode(mode) {
    this.mode = mode;
    this.element(".board-mode").querySelectorAll("button").forEach(button=>
      button.setAttribute("aria-pressed",button.dataset.mode === mode));
    this.renderPicks();
    this.load();
  }

  renderPicks() {
    this.updateColors();
    const search=this.element(".board-lookup input").value;
    const visible=Array.from(this.picks).filter(([id,name])=>matchesInstrument(name,id,search));
    const cards=visible.map(([id,name])=>{
      const selected = this.mode === "multi" ? this.selected.has(id) : id === this.single;
      return instrumentCard(id, name, lookup.get(id), selected, ()=>{
        if(this.mode==="single") this.single=id;
        else if(this.selected.has(id)) this.selected.delete(id);
        else this.selected.add(id);
        this.renderPicks();
        this.load();
      }, this.color(id));
    });
    const known=new Set(visible.map(([id])=>id));
    this.searchRows.filter(row=>!known.has(row.id)).forEach(row=>cards.push(
      instrumentCard(row.id,row.name,lookup.get(row.id),false,()=>this.addInstrument(row))
    ));
    this.element(".board-pick-count").textContent = search.trim() ? cards.length+" 条匹配" : this.picks.size+" 个标的";
    if (!cards.length) cards.push(node("p","暂无匹配标的","note instrument-empty"));
    replaceInstrumentCards(this.element(".board-picks"),cards);
    this.renderSummary();
  }

  renderSummary() {
    const single=this.mode==="single", quote=lookup.get(this.single), line=this.lines[0];
    const name=this.element(".board-instrument h3"), symbol=this.element(".board-symbol");
    const current=this.element(".board-current"), legend=this.element(".board-legend");
    name.textContent=single ? this.picks.get(this.single) : "区间走势对比";
    symbol.textContent=single ? (quote?.code || this.single.slice(2).replace(/^\./,""))+" · 日线"
      : "已选 "+this.selected.size+" 个标的";
    current.hidden=!single;
    legend.hidden=single;
    if (!single) return;
    const last=line?.raw.at(-1);
    const price=quote?.value ?? last?.value;
    current.querySelector("strong").textContent = price == null ? "—" : format(price)+" "+(quote?.unit || this.config.unit);
    const movement = current.querySelector("span");
    movement.replaceChildren(...(quote?.percent == null ? [] : [closeChange(quote.percent)]));
    current.querySelector("small").textContent = quote ? formatTime(quote) : last ? last.date+" · 日线收盘" : "";
  }

  enableLookup() {
    const form=this.element(".board-lookup"),input=form.querySelector("input");
    const status=this.element(".board-lookup-status");
    let timer, sequence=0;
    const search=async()=>{
      const q=input.value.trim();
      const ticket=++sequence;
      if (!q) return;
      status.textContent="正在搜索…";
      try{
        const result=await api("search?market="+this.config.id+"&q="+encodeURIComponent(q));
        if (ticket!==sequence || q!==input.value.trim()) return;
        this.searchRows=result.rows;
        status.textContent="";
        this.renderPicks();
      }catch(_){
        if(ticket===sequence && q===input.value.trim()) status.textContent="在线搜索暂不可用，可查看已载入的匹配标的";
      }
    };
    input.addEventListener("input",()=>{
      sequence++;
      this.searchRows=[];
      status.textContent="";
      this.renderPicks();
      clearTimeout(timer);
      if (input.value.trim()) timer=setTimeout(search,280);
    });
    form.addEventListener("submit",event=>{
      event.preventDefault();
      clearTimeout(timer);
      search();
    });
  }

  async addInstrument(row){
    const ticket=++this.addTicket,status=this.element(".board-lookup-status");
    status.textContent="正在获取报价…";
    try {
      const quote=lookup.get(row.id) || await api("quote?symbol="+encodeURIComponent(row.id));
      if (ticket!==this.addTicket) return;
      lookup.set(row.id,quote);
      this.picks.set(row.id,row.name);
      window.dispatchEvent(new CustomEvent("market-custom-instrument",{detail:{...quote, group:this.config.id}}));
      if(this.mode==="single") this.single=row.id;
      else this.selected.add(row.id);
      this.element(".board-lookup input").value="";
      this.searchRows=[];
      status.textContent="";
      this.renderPicks();
      this.load();
    } catch (_) {
      if(ticket===this.addTicket) status.textContent="暂未取得该标的报价";
    }
  }

  async load() {
    const ticket = ++this.ticket;
    const ids = this.mode === "multi" ? Array.from(this.selected) : [this.single];
    this.element(".board-axis").textContent = this.mode === "multi" ? "区间累计涨跌幅" : "日线价格 · " + this.config.unit;
    this.element(".board-note").textContent = "";
    this.element(".board-retry").hidden = true;
    const valuation=this.element(".board-valuation");
    valuation.hidden=true;
    valuation.open=false;
    this.element(".board-insights .board-metrics").replaceChildren();
    this.element(".board-legend").replaceChildren();
    this.tooltip.hidden = true;
    this.highlight = null;
    delete this.canvas.dataset.highlight;
    this.lines = [];
    this.renderSummary();
    this.draw();
    const message = this.element(".board-empty");
    message.textContent = ids.length ? "正在加载日线…" : "在列表中选择标的";
    if (!ids.length) return;
    const results = await Promise.allSettled(ids.map(marketHistory));
    if (ticket !== this.ticket) return;
    const failed = [];
    const available = results.flatMap((result,index)=>{
      const id=ids[index];
      if (result.status !== "fulfilled" || result.value.points.length < 2) {
        failed.push(this.picks.get(id));
        return [];
      }
      return [{id, ...result.value}];
    });
    this.element(".board-retry").hidden = !failed.length;
    if (!available.length) {
      message.textContent = "暂未取得日线";
      return;
    }
    const latest = available.map(item=>item.points.at(-1).date).sort().at(-1);
    const {start:requestedStart,end} = this.timeline.setLatest(latest);
    let start = requestedStart;
    if (available.length > 1) {
      const otherDates = available.slice(1).map(item=>new Set(item.points.map(point=>point.date)));
      const common = available[0].points.find(point=>point.date >= requestedStart && point.date <= end && otherDates.every(dates=>dates.has(point.date)));
      if (!common) {
        message.textContent = "所选标的在该区间没有共同交易日";
        return;
      }
      start = common.date;
    }
    this.lines = available.flatMap(item=>{
      const raw=item.points.filter(point=>point.date>=start && point.date<=end);
      if (!raw.length) {
        failed.push(this.picks.get(item.id));
        return [];
      }
      const base=raw[0].value;
      const points=this.mode==="multi" ? raw.map(point=>({...point,value:100*(point.value/base-1)})) : raw;
      return [{id:item.id,name:this.picks.get(item.id),color:this.color(item.id),points,raw,cached:item.cached}];
    });
    this.element(".board-retry").hidden = !results.some(result=>result.status === "rejected");
    if (!this.lines.length) {
      message.textContent = "所选区间内的日线不足";
      return;
    }
    message.textContent = "";
    this.element(".board-legend").replaceChildren(...this.lines.map(line=>{
      const chip=node("span",null,"legend-item");
      const marker=node("span",null,"line-key");
      marker.style.setProperty("--line-color",line.color);
      chip.append(marker, node("span",line.name));
      if (this.mode === "multi") chip.append(change(line.points.at(-1).value));
      return chip;
    }));
    const from=this.lines.map(line=>line.points[0].date).sort()[0];
    const through=this.lines.map(line=>line.points.at(-1).date).sort().at(-1);
    const notes=[from+" 至 "+through, "腾讯财经日线"];
    if (this.mode==="multi") notes.push("以显示区间的首个共同交易日为基准");
    const stale=this.lines.filter(line=>line.cached).map(line=>line.name);
    if (stale.length) notes.push(stale.join("、")+"使用上次保存的日线");
    if (failed.length) notes.push(failed.join("、")+"日线不足或暂不可用");
    this.element(".board-note").textContent=notes.join(" · ");
    this.canvas.setAttribute("aria-label",this.config.title+"，"+from+"至"+end+"，"+this.lines.map(line=>line.name).join("、"));
    this.renderSummary();
    this.renderDetails(ticket);
    this.draw();
  }

  renderDetails(ticket) {
    const details=this.element(".board-insights .board-metrics");
    const add=(parent,label,value)=>{
      const item=node("div");
      item.append(node("dt",label),node("dd",value));
      parent.append(item);
    };
    if (this.mode==="multi"){
      const values=this.lines.map(line=>line.points.at(-1).value);
      add(details,"对比标的",values.length+" 个");
      add(details,"区间上涨",values.filter(value=>value>0).length+" 个");
      add(details,"区间下跌",values.filter(value=>value<0).length+" 个");
      add(details,"区间持平",values.filter(value=>value===0).length+" 个");
      return;
    }
    const line=this.lines[0], prices=line.raw.map(point=>point.value), last=prices.at(-1);
    add(details,"最新日线",format(last)+" "+this.config.unit);
    add(details,"区间涨跌",percent(100*(last/prices[0]-1)));
    add(details,"区间最高收盘",format(Math.max(...prices)));
    add(details,"区间最低收盘",format(Math.min(...prices)));
    if (this.config.id === "china") api("valuation?symbol="+encodeURIComponent(line.id)).then(data=>{
      if (this.ticket !== ticket) return;
      const disclosure=this.element(".board-valuation"), metrics=disclosure.querySelector("dl");
      metrics.replaceChildren();
      add(metrics,"市盈率 TTM",format(data.pe));
      add(metrics,"市净率",format(data.pb));
      add(metrics,"换手率",data.turnover==null ? "—" : format(data.turnover)+"%");
      add(metrics,"市值 · 亿元",format(data.marketCapBillions));
      disclosure.hidden=false;
    }).catch(()=>{});
  }

  draw() {
    const {width,height}=this.canvas.getBoundingClientRect();
    if (!width || !height) return;
    const dpr=window.devicePixelRatio || 1;
    const ctx=this.canvas.getContext("2d");
    this.canvas.width=Math.round(width*dpr);
    this.canvas.height=Math.round(height*dpr);
    ctx.scale(dpr,dpr);
    this.chartGeometry=null;
    if (!this.lines.length) return;
    const points=this.lines.flatMap(line=>line.points);
    const values=points.map(point=>point.value);
    const min=Math.min(...values),max=Math.max(...values),pad=(max-min)*.1 || Math.max(Math.abs(max)*.01,.1);
    const low=min-pad, high=max+pad;
    const left=64, right=width-16, top=15, bottom=height-32;
    const {dates,x}=calendarAxis(this.timeline.bounds,left,right);
    const y=value=>top+(high-value)*(bottom-top)/(high-low);
    ctx.font="13px "+getComputedStyle(document.documentElement).getPropertyValue("--dashboard-font");
    ctx.textAlign="right";
    ctx.textBaseline="middle";
    for(let i=0;i<5;i++){
      const value=low+(high-low)*i/4;
      ctx.strokeStyle="#bdd3bf25";
      ctx.beginPath();ctx.moveTo(left,y(value));ctx.lineTo(right,y(value));ctx.stroke();
      ctx.fillStyle="#bdc8c0";
      ctx.fillText(format(value)+(this.mode==="multi"?"%":""),left-6,y(value));
    }
    if (this.mode==="multi" && low<0 && high>0){
      ctx.strokeStyle="#d6d8c45e";
      ctx.setLineDash([4,4]);
      ctx.beginPath();ctx.moveTo(left,y(0));ctx.lineTo(right,y(0));ctx.stroke();
      ctx.setLineDash([]);
    }
    drawDateTicks(ctx,dates,left,right,top,bottom,height-14);
    if (this.mode === "single"){
      const line=this.lines[0];
      ctx.beginPath();
      line.points.forEach((point,i)=>i?ctx.lineTo(x(point.date),y(point.value)):ctx.moveTo(x(point.date),y(point.value)));
      ctx.lineTo(x(line.points.at(-1).date),bottom);
      ctx.lineTo(x(line.points[0].date),bottom);
      ctx.closePath();
      const fill=ctx.createLinearGradient(0,top,0,bottom);
      fill.addColorStop(0,line.color+"48");
      fill.addColorStop(1,line.color+"05");
      ctx.fillStyle=fill;
      ctx.fill();
    }
    const traces=this.lines.map(line=>({line, points:line.points.map((point,i)=>({
      ...point, raw:line.raw[i].value,x:x(point.date),y:y(point.value)
    }))}));
    const ordered=this.highlight ? [...traces.filter(t=>t.line.id!==this.highlight.id),...traces.filter(t=>t.line.id===this.highlight.id)] : traces;
    for (const trace of ordered) {
      const highlighted=trace.line.id===this.highlight?.id;
      ctx.globalAlpha=this.highlight && !highlighted ? .25 : 1;
      ctx.beginPath();
      ctx.strokeStyle=trace.line.color;
      ctx.lineWidth=highlighted ? 3.5 : 2;
      trace.points.forEach((point,i)=>i?ctx.lineTo(point.x,point.y):ctx.moveTo(point.x,point.y));
      ctx.stroke();
      const marker=highlighted ? trace.points.find(point=>point.date===this.highlight.date) : trace.points.length===1 ? trace.points[0] : null;
      if (marker){
        ctx.beginPath();ctx.arc(marker.x,marker.y,4,0,Math.PI*2);ctx.fillStyle=trace.line.color;ctx.fill();
      }
    }
    ctx.globalAlpha=1;
    this.chartGeometry={left,right,top,bottom,traces};
  }

  clearHover(){
    this.tooltip.hidden=true;
    if(this.highlight){
      this.highlight=null;
      delete this.canvas.dataset.highlight;
      this.draw();
    }
  }

  hover(event) {
    const g=this.chartGeometry;
    if (!g) return;
    const x=event.offsetX,y=event.offsetY;
    let best=null,distance=event.pointerType==="touch"?24:13;
    if (x<g.left-12 || x>g.right+12 || y<g.top-12 || y>g.bottom+12) return this.clearHover();
    for (const {line,points} of g.traces){
      for(let i=0;i<points.length;i++){
        const a=points[i],b=points[i+1] || a;
        if(x<Math.min(a.x,b.x)-distance || x>Math.max(a.x,b.x)+distance) continue;
        const dx=b.x-a.x,dy=b.y-a.y;
        const t=Math.min(1,Math.max(0,((x-a.x)*dx+(y-a.y)*dy)/(dx*dx+dy*dy || 1)));
        const d=Math.hypot(x-a.x-t*dx,y-a.y-t*dy);
        if(d<=distance){distance=d;best={line,point:t<.5?a:b};}
      }
    }
    if(!best) return this.clearHover();
    const {line,point}=best;
    if(this.highlight?.id!==line.id || this.highlight?.date!==point.date){
      this.highlight={id:line.id,date:point.date};
      this.canvas.dataset.highlight=line.id;
      this.draw();
    }
    const metric=this.mode==="multi" ? "区间涨跌 "+percent(point.value) : format(point.value)+" "+this.config.unit;
    const label=node("strong",line.name);
    label.style.color=line.color;
    const detail=node("span",this.mode==="multi" ? metric+" · 价格 "+format(point.raw)+" "+this.config.unit : metric);
    this.tooltip.replaceChildren(label,node("span",point.date),detail);
    this.tooltip.hidden=false;
    this.tooltip.style.left=Math.max(7,Math.min(x+13,this.canvas.clientWidth-this.tooltip.offsetWidth-7))+"px";
    this.tooltip.style.top=Math.max(7,Math.min(y-12,this.canvas.clientHeight-this.tooltip.offsetHeight-7))+"px";
  }

}

if ($("market-boards") && location.hash !== "#factor-title") {
  const boards=trendBoards.map(config=>new MarketBoard(config,$("market-boards")));
  window.addEventListener("market-quotes",()=>boards.forEach(board=>{
    const key={china:"沪深市场",usa:"美国市场"}[board.config.id];
    for(const item of snapshots?.groups[key] || []){
      if (item.seriesType==="security" && !board.picks.has(item.id)) board.picks.set(item.id,item.name);
    }
    board.renderPicks();
  }));
  window.addEventListener("market-history-refresh",()=>{
    marketSeries.clear();
    boards.forEach(board=>board.load());
  });
  window.addEventListener("market-index-select",event=>{
    const board=boards[0];
    if (!board.picks.has(event.detail)) return;
    board.single=event.detail;
    board.setMode("single");
    board.panel.scrollIntoView({block:"start"});
  });
}
