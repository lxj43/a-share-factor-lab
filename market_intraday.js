"use strict";

const intradayGroups=[
  ["全部","全部标的"],["indices","主要指数"],["沪深市场","沪深 A 股"],["美国市场","美股"],
  ["中证 800 行业","A 股行业"],["中国行业","A 股细分板块"],["美国行业","美股行业 ETF"],
  ["宏观利率","宏观利率"],["大宗商品","大宗商品"],["外汇市场","外汇"]
];

function sessionMinute(label){
  const [hour,minute]=label.split(":").map(Number);
  return hour*60+minute;
}
function sessionLabel(minutes){
  const minutesInDay=(minutes+1440)%1440;
  return String(Math.floor(minutesInDay/60)).padStart(2,"0")+":"+String(minutesInDay%60).padStart(2,"0");
}

class IntradayBoard {
  constructor(){
    this.chart=$("intraday-chart");
    this.group=$("intraday-group");
    this.search=$("intraday-search");
    this.boardRows=[];
    this.custom=new Map();
    this.searchRows=[];
    this.page=1;
    this.total=0;
    this.ticket=0;
    this.pageTicket=0;
    this.searchTicket=0;
    this.group.replaceChildren(...intradayGroups.map(([id,name])=>new Option(name,id)));
    this.group.addEventListener("change",()=>{
      this.searchRows=[];
      this.searchTicket++;
      this.search.value="";
      if(this.group.value==="中国行业") this.loadBoards(1);
      if(externalMarkets[this.group.value]) refreshExternalQuotes(this.group.value);
      this.render();
    });
    let debounce;
    this.search.addEventListener("input",()=>{
      this.searchTicket++;
      this.searchRows=[];
      this.render();
      clearTimeout(debounce);
      debounce=setTimeout(()=>this.remoteSearch(),280);
    });
    $("intraday-prev").addEventListener("click",()=>this.loadBoards(this.page-1));
    $("intraday-next").addEventListener("click",()=>this.loadBoards(this.page+1));
    this.chart.addEventListener("pointermove",event=>this.hover(event));
    this.chart.addEventListener("pointerleave",()=>$("intraday-tip").hidden=true);
    new ResizeObserver(()=>this.draw()).observe(this.chart);
    window.addEventListener("market-quotes",()=>this.render());
    window.addEventListener("market-custom-instrument",event=>{
      this.custom.set(event.detail.id,event.detail);
      this.render();
    });
    window.addEventListener("market-history-refresh",()=>{if(this.open) this.select(this.active);});
    new IntersectionObserver(entries=>{
      if(entries.some(entry=>entry.isIntersecting)){
        if(!this.open){
          this.open=true;
          this.select(this.active);
          this.loadBoards(1);
          for(const market of Object.keys(externalMarkets)) refreshExternalQuotes(market);
        }
      }
    },{rootMargin:"250px"}).observe($("intraday"));
    setInterval(()=>{if(this.open && !document.hidden && $("intraday").getBoundingClientRect().top<innerHeight+250)this.select(this.active);},60000);
    this.active={id:"sh000300",name:"沪深 300",unit:"点"};
    this.render();
  }

  async loadBoards(page){
    const ticket=++this.pageTicket;
    try{
      const result=await api("industries?page="+page);
      if(ticket!==this.pageTicket)return;
      this.boardRows=result.rows;
      this.total=result.total;
      this.page=page;
      result.rows.forEach(item=>lookup.set(item.id,item));
      this.render();
    }catch(_){}
  }

  async remoteSearch(){
    const q=this.search.value.trim(),g=this.group.value,ticket=++this.searchTicket;
    if(!q)return;
    const markets={indices:["indices"],"沪深市场":["china"],"美国市场":["usa"],"中国行业":["board"],"全部":["china","usa","board"]}[g] || [];
    const results=await Promise.allSettled(markets.map(market=>api("search?market="+market+"&q="+encodeURIComponent(q))));
    if(ticket!==this.searchTicket || q!==this.search.value.trim() || g!==this.group.value)return;
    this.searchRows=results.flatMap(item=>item.status==="fulfilled"?item.value.rows:[]);
    this.render();
  }

  rowsFor(group){
    if(group==="indices")return trendBoards[0].picks.map(([id,name])=>lookup.get(id)||{id,name,unit:"点"});
    if(group==="沪深市场" || group==="美国市场"){
      return marketGroupRows(group).filter(item=>item.seriesType==="security");
    }
    return marketGroupRows(group,this.boardRows);
  }

  render(){
    const group=this.group.value,q=this.search.value;
    const pool=group==="全部"?intradayGroups.slice(1).flatMap(([id])=>this.rowsFor(id)):[...this.rowsFor(group)];
    const keys={"沪深市场":"china","美国市场":"usa",indices:"indices"};
    pool.push(...Array.from(this.custom.values()).filter(item=>group==="全部" || item.group===keys[group]));
    const rows=uniqueInstruments([...pool.filter(item=>matchesInstrument(item.name,item.id,q)),...this.searchRows])
      .map(item=>lookup.get(item.id)||item);
    const cards=rows.map(item=>instrumentCard(item.id,item.name,item,item.id===this.active.id,()=>this.select(item)));
    if(!cards.length)cards.push(node("p",q?"暂无匹配标的":"正在读取标的","note instrument-empty"));
    replaceInstrumentCards($("intraday-picks"),cards);
    $("intraday-count").textContent=rows.length+" 个标的";
    $("intraday-pages").hidden=!(group==="中国行业" || group==="全部") || this.total<=100 || Boolean(q.trim());
    const last=Math.ceil(this.total/100);
    $("intraday-prev").disabled=this.page<=1;
    $("intraday-next").disabled=this.page>=last;
    $("intraday-page").textContent=this.page+" / "+last;
  }

  async select(item){
    const ticket=++this.ticket;
    const same=this.active.id===item.id;
    this.active=item;
    $("intraday-name").textContent=item.name;
    $("intraday-tip").hidden=true;
    if(!same || !this.data){
      this.data=null;
      $("intraday-value").textContent="—";
      $("intraday-change").textContent="";
      $("intraday-source").textContent="";
      $("intraday-session").textContent="";
      $("intraday-status").textContent="正在加载分时…";
      this.draw();
    }
    this.render();
    try{
      if(item.id===macroRate.id){
        const rate=await api("macro");
        if(ticket!==this.ticket)return;
        const last=rate.points.at(-1);
        $("intraday-value").textContent=format(last.value)+"%";
        $("intraday-session").textContent=last.date+" · FRED 日频";
        $("intraday-status").textContent="此序列按日发布，暂无开盘至收盘分时数据";
        return;
      }
      const data=await api("intraday?symbol="+encodeURIComponent(item.id));
      if(ticket!==this.ticket)return;
      this.data=data;
      const last=data.points.at(-1),first=data.points[0];
      const quote=lookup.get(item.id);
      const unit=item.unit || quote?.unit || (item.id.startsWith("us")?"USD":item.id.startsWith("BK")?"点":"CNY");
      $("intraday-value").textContent=formatValue(last.value,unit)+" "+unit;
      $("intraday-change").textContent="较开盘首笔 "+percent((last.value/first.value-1)*100);
      $("intraday-session").textContent=data.date+" · "+data.zone+" · "+data.open+" — "+data.close+(data.overnight?"（次日）":"");
      $("intraday-source").textContent=data.source+" · 最后记录 "+last.time+(data.cached?" · 上次保存":"");
      $("intraday-status").textContent="";
      this.chart.setAttribute("aria-label",item.name+"，"+data.date+"，"+data.open+"开盘至"+data.close+"收盘，最后记录 "+last.time+" "+format(last.value));
      this.draw();
    }catch(_){
      if(ticket!==this.ticket)return;
      if(this.data) $("intraday-source").textContent+=" · 更新暂不可用";
      else $("intraday-status").textContent="暂未取得该标的的分时数据";
    }
  }

  draw(){
    const canvas=this.chart,{width,height}=canvas.getBoundingClientRect();
    if(!width || !height)return;
    const dpr=devicePixelRatio || 1,ctx=canvas.getContext("2d");
    canvas.width=Math.round(width*dpr);
    canvas.height=Math.round(height*dpr);
    ctx.scale(dpr,dpr);
    this.geometry=null;
    if(!this.data)return;
    const {open,close,overnight,points,segments}=this.data;
    const begin=sessionMinute(open),end=sessionMinute(close)+(overnight?1440:0);
    if(end<=begin)return;
    const logical=time=>{
      const minute=sessionMinute(time);
      return minute<begin && overnight?minute+1440:minute;
    };
    const left=66,right=width-15,top=15,bottom=height-31;
    const values=points.map(point=>point.value),lo=Math.min(...values),hi=Math.max(...values);
    const pad=(hi-lo)*.09 || Math.abs(hi)*.01 || .01,low=lo-pad,high=hi+pad;
    const x=minute=>left+(right-left)*(minute-begin)/(end-begin);
    const y=value=>top+(bottom-top)*(high-value)/(high-low);
    ctx.font="13px "+getComputedStyle(document.documentElement).getPropertyValue("--dashboard-font");
    ctx.textBaseline="middle";
    ctx.textAlign="right";
    for(let i=0;i<5;i++){
      const value=low+(high-low)*i/4;
      ctx.strokeStyle="#bdd3bf25";ctx.beginPath();ctx.moveTo(left,y(value));ctx.lineTo(right,y(value));ctx.stroke();
      ctx.fillStyle="#bdc8c0";ctx.fillText(formatValue(value,this.active.unit),left-7,y(value));
    }
    const tickCount=width<550?5:7;
    const ticks=segments.length?[begin,sessionMinute("10:30"),sessionMinute("11:30"),sessionMinute("13:00"),sessionMinute("14:00"),end]:
      Array.from({length:tickCount},(_,index)=>begin+Math.round((end-begin)*index/(tickCount-1)));
    const labels=width<450 && segments.length?[begin,sessionMinute("11:30"),sessionMinute("13:00"),end]:ticks;
    labels.forEach((minute,index)=>{
      const xx=x(minute);
      ctx.strokeStyle="#bdd3bf18";ctx.beginPath();ctx.moveTo(xx,top);ctx.lineTo(xx,bottom);ctx.stroke();
      ctx.textAlign=index===0?"left":index===labels.length-1?"right":"center";
      ctx.fillText(sessionLabel(minute),xx,height-12);
    });
    const rendered=points.map(point=>({...point,minute:logical(point.time)}))
      .filter(point=>point.minute>=begin && point.minute<=end);
    ctx.strokeStyle="#e4bd77";ctx.lineWidth=2;ctx.beginPath();
    rendered.forEach((point,i)=>{
      const prev=rendered[i-1];
      const lunch=prev && segments.some(([a,b])=>prev.minute<=sessionMinute(a) && point.minute>=sessionMinute(b));
      if(!prev || lunch)ctx.moveTo(x(point.minute),y(point.value));
      else ctx.lineTo(x(point.minute),y(point.value));
    });
    ctx.stroke();
    if(rendered.length===1){
      const p=rendered[0];ctx.beginPath();ctx.arc(x(p.minute),y(p.value),3,0,Math.PI*2);ctx.fillStyle="#e4bd77";ctx.fill();
    }
    this.geometry={points:rendered,x,y};
  }

  hover(event){
    if(!this.geometry)return;
    const {points,x,y}=this.geometry,tip=$("intraday-tip");
    const point=points.reduce((best,p)=>!best || Math.abs(x(p.minute)-event.offsetX)<Math.abs(x(best.minute)-event.offsetX) ? p : best,null);
    if(!point || Math.abs(x(point.minute)-event.offsetX)>17 || Math.abs(y(point.value)-event.offsetY)>26){tip.hidden=true;return;}
    tip.replaceChildren(node("strong",this.active.name),node("span",point.time+" · "+format(point.value)));
    tip.hidden=false;
    tip.style.left=Math.max(6,Math.min(event.offsetX+12,this.chart.clientWidth-tip.offsetWidth-6))+"px";
    tip.style.top=Math.max(6,Math.min(event.offsetY+10,this.chart.clientHeight-tip.offsetHeight-6))+"px";
  }
}

if ($("intraday") && location.hash !== "#factor-title") new IntradayBoard();
