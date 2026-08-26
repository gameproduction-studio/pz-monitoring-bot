(() => {
  "use strict";

  const app = {
    data:null, view:"overview", language:"RU", resources:[], vehicleDetails:new Map(),
    healthKey:null, poll:null
  };
  const $ = (selector, root=document) => root.querySelector(selector);
  const $$ = (selector, root=document) => [...root.querySelectorAll(selector)];
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch]));
  const num = (value, digits=0) => Number.isFinite(Number(value))
    ? new Intl.NumberFormat(undefined,{maximumFractionDigits:digits}).format(Number(value)) : "—";
  const pct = (value) => Number.isFinite(Number(value)) ? Math.max(0,Math.min(100,Number(value))) : 0;
  const baseName = (path) => String(path || "").split("/").pop();
  const dict = () => window.PZ_I18N.catalog[app.language] || window.PZ_I18N.fallback;
  const t = (key) => key.split(".").reduce((value, part) => value && value[part], dict()) ?? key;
  const get = (key, fallback) => key.split(".").reduce((value,part)=>value && value[part], app.data) ?? fallback;

  function setConnection(mode, label) {
    const el = $("#connection");
    el.className = "connection " + mode;
    $("span", el).textContent = label;
  }

  function applyLanguage(code) {
    app.language = (code || "EN").toUpperCase();
    document.documentElement.lang = app.language.toLowerCase();
    $$("[data-i18n]").forEach(el => { el.textContent = t(el.dataset.i18n); });
    $("#view-title").textContent = t("titles." + app.view);
    render();
  }

  function languageName(code) {
    const tags = {AR:"ar",CA:"ca",CH:"zh-Hant",CN:"zh-Hans",CS:"cs",DA:"da",DE:"de",EN:"en",
      ES:"es",ES_CL:"es-CL",ES_MX:"es-MX",FI:"fi",FR:"fr",HU:"hu",ID:"id",IT:"it",JP:"ja",
      KO:"ko",NL:"nl",NO:"no",PL:"pl",PT:"pt",PTBR:"pt-BR",RO:"ro",RU:"ru",STREW:"en",
      TH:"th",TR:"tr",UA:"uk"};
    try {
      return new Intl.DisplayNames([tags[app.language] || "en"], {type:"language"}).of(tags[code] || code) || code;
    } catch (_) { return code; }
  }

  function browserLanguage() {
    const raw=(navigator.language||"en").replace("-","_").toUpperCase();
    const aliases={UK:"UA",JA:"JP",ZH_CN:"CN",ZH_TW:"CH",ZH_HK:"CH"};
    const code=aliases[raw]||aliases[raw.split("_")[0]]||raw.split("_")[0];
    return window.PZ_I18N.catalog[code] ? code : "EN";
  }

  function setupLanguage() {
    const select = $("#language");
    const available = get("language.available", Object.keys(window.PZ_I18N.catalog));
    select.innerHTML = available.map(code => `<option value="${esc(code)}">${esc(languageName(code))} · ${esc(code)}</option>`).join("");
    select.value = app.language;
    select.addEventListener("change", () => {
      localStorage.setItem("pz-organizer-language", select.value);
      applyLanguage(select.value);
    });
  }

  function section(name) { return get("sections." + name, {}) || {}; }
  function character() { return section("character").character || get("bootstrap.overview.character", {}) || {}; }
  function bases() { return section("bases").bases || get("bootstrap.overview.bases", []) || []; }

  function vehicles() {
    const source = section("vehicles").owned || get("bootstrap.overview.vehicles", []) || [];
    const unique = new Map();
    source.forEach(vehicle => {
      const key = vehicle.detailFile || vehicle.vehicleId || vehicle.name || vehicle.scriptFullType;
      const current = unique.get(key);
      if (!current || (vehicle.loadedNow && !current.loadedNow)) unique.set(key, vehicle);
    });
    return [...unique.values()];
  }

  function metric(label, value, detail, tone="good") {
    return `<article class="metric ${tone}"><label>${esc(label)}</label><strong>${esc(value)}</strong><small>${esc(detail || "")}</small></article>`;
  }

  function statePill(loaded) {
    return `<span class="pill ${loaded ? "live":"stale"}">${esc(loaded ? t("current"):t("stale"))}</span>`;
  }

  function condition(value) {
    const v = pct(value);
    return `<div class="inline-bar"><div class="bar ${v < 40 ? "warn":""}"><i style="width:${v}%"></i></div><span class="mono">${num(v,1)}%</span></div>`;
  }

  function empty() {
    return $("#empty-template").content.cloneNode(true);
  }

  function renderOverview() {
    const c = character();
    const baseRows = bases();
    const vehicleRows = vehicles();
    const food = section("food");
    const weight = Number(c.carryingWeight || 0), max = Number(c.maxWeight || 0);
    const containerCount = baseRows.reduce((n,b)=>n+Number(b.containerCount||0),0);
    const itemCount = baseRows.reduce((n,b)=>n+Number(b.itemInstances||0),0);
    const calories = Number(food.totalCaloriesReportedByGame || food.edibleStock?.calories || 0);
    const inventory = section("character").inventorySummary || [];
    const equipped = inventory.filter(row => row.equipped).slice(0,8);
    return `
      <div class="grid metrics">
        ${metric(t("carrying"), `${num(weight,2)} / ${num(max,0)}`, c.dead ? "DEAD":"", weight > max*.9 ? "warn":"good")}
        ${metric(t("containers"), num(containerCount), `${baseRows.length} × ${t("bases")}`)}
        ${metric(t("items"), num(itemCount), `${t("resources")}: ${num(section("resources").resourceGroupCount || app.resources.length)}`)}
        ${metric(t("calories"), num(calories,0), t("caloriesShort"), calories ? "good":"warn")}
      </div>
      <div class="grid two-col">
        <article class="card">
          <div class="card-head"><h2>${esc(t("character"))}</h2><span class="kicker">${esc(t("gameBuild"))} ${esc(get("bootstrap.game.build","—"))}</span></div>
          <div class="character">
            <div class="silhouette" aria-hidden="true"></div>
            <div>
              <h3>${esc(c.name || [c.forename,c.surname].filter(Boolean).join(" ") || "—")}</h3>
              <div class="muted mono">${esc(t("coordinates"))}: ${num(c.position?.x,1)} / ${num(c.position?.y,1)} / ${num(c.position?.z,0)}</div>
              <div class="bar ${weight > max*.9 ? "warn":""}"><i style="width:${max ? pct(weight/max*100):0}%"></i></div>
            </div>
          </div>
          <div class="list" style="margin-top:18px">
            ${equipped.map(row=>`<div class="list-row"><div><strong>${esc(row.name_ru || row.name || row.fullType)}</strong><small>${esc((row.locations_ru||[]).map(x=>x.name_ru).join(" · "))}</small></div><span class="pill live">${esc(t("equipped"))}</span></div>`).join("") || `<p class="muted">${esc(t("noData"))}</p>`}
          </div>
        </article>
        <article class="card">
          <div class="card-head"><h2>${esc(t("operational"))}</h2><span class="status-line"><i class="dot"></i>${esc(t("current"))}</span></div>
          <div class="list">
            ${baseRows.map(b=>`<div class="list-row"><div><strong>${esc(b.name)}</strong><small>${num(b.containerCount)} ${esc(t("containers").toLowerCase())} · R${num(b.radius)}</small></div>${statePill((b.loadedContainersNow||0)>0)}</div>`).join("")}
            ${vehicleRows.map(v=>`<div class="list-row"><div><strong>${esc(v.name || v.displayName)}</strong><small>${esc(t("fuel"))} ${num(v.fuel?.percent,1)}% · ${esc(t("overall"))} ${num(v.overallConditionPercent,1)}%</small></div>${statePill(v.loadedNow)}</div>`).join("")}
          </div>
        </article>
      </div>`;
  }

  function renderBases() {
    const rows = bases();
    if (!rows.length) return null;
    return `<div class="grid">${rows.map(base => `
      <article class="card">
        <div class="card-head">
          <div><span class="kicker">${esc(t("base"))} · R${num(base.radius)}</span><h2>${esc(base.name)}</h2></div>
          ${statePill((base.loadedContainersNow||0)>0)}
        </div>
        <div class="grid metrics">
          ${metric(t("containers"),num(base.containerCount),`${t("loaded")}: ${num(base.loadedContainersNow)}`)}
          ${metric(t("items"),num(base.itemInstances),"")}
          ${metric(t("radius"),num(base.radius),`${t("coordinates")}: ${num(base.center?.x)}, ${num(base.center?.y)}`)}
          ${metric(t("lastKnown"),num(base.lastKnownContainers||0),t("containers"),(base.lastKnownContainers||0)>0?"warn":"good")}
        </div>
        <div class="table-wrap" style="margin-top:16px"><table>
          <thead><tr><th>${esc(t("name"))}</th><th>${esc(t("state"))}</th><th>${esc(t("items"))}</th><th>${esc(t("coordinates"))}</th></tr></thead>
          <tbody>${(base.containers||[]).map(c=>`<tr><td><strong>${esc(c.displayName || c.containerType)}</strong><br><small class="muted mono">${esc(c.containerType||c.kind||"")}</small></td><td>${statePill(c.loadedNow)}</td><td class="qty">${num(c.itemInstances)}</td><td class="mono muted">${esc(typeof c.position === "object" ? `${c.position.x}, ${c.position.y}, ${c.position.z}` : c.position)}</td></tr>`).join("")}</tbody>
        </table></div>
      </article>`).join("")}</div>`;
  }

  function renderVehicles() {
    const rows = vehicles();
    if (!rows.length) return null;
    return `<div class="grid">${rows.map(v=>`
      <article class="card vehicle-card">
        <div>
          <div class="card-head"><div><span class="kicker">${esc(v.displayName || v.scriptFullType || "")}</span><h2>${esc(v.name || v.displayName)}</h2></div>${statePill(v.loadedNow)}</div>
          <div class="gauges">
            <div class="gauge"><label>${esc(t("fuel"))}</label><strong>${num(v.fuel?.percent,1)}%</strong><div class="bar"><i style="width:${pct(v.fuel?.percent)}%"></i></div></div>
            <div class="gauge"><label>${esc(t("battery"))}</label><strong>${num(v.batteryChargePercent,1)}%</strong><div class="bar"><i style="width:${pct(v.batteryChargePercent)}%"></i></div></div>
            <div class="gauge"><label>${esc(t("overall"))}</label><strong>${num(v.overallConditionPercent,1)}%</strong><div class="bar ${pct(v.overallConditionPercent)<40?"warn":""}"><i style="width:${pct(v.overallConditionPercent)}%"></i></div></div>
          </div>
          ${(v.alerts||[]).map(a=>`<div class="alert">${esc(a.message_ru || a.message || a.kind)}</div>`).join("") || `<p class="muted" style="margin-top:14px">${esc(t("noAlerts"))}</p>`}
        </div>
        <div>
          <div class="card-head"><h2>${esc(t("cargo"))}</h2><span class="mono muted">${num(v.position?.x,0)} / ${num(v.position?.y,0)}</span></div>
          <div class="list">${(v.cargoContainers||[]).map(c=>`<div class="list-row"><div><strong>${esc(c.name_ru || c.name || c.containerId)}</strong><small>${esc(t("items"))}: ${num(c.itemInstances)} · max ${num(c.capacity)}</small></div>${statePill(c.loadedNow)}</div>`).join("") || `<p class="muted">${esc(t("noData"))}</p>`}</div>
        </div>
      </article>`).join("")}</div>`;
  }

  function renderFood() {
    const food = section("food"), fields = food.foodSummaryFields || [];
    const rows = (food.foodSummaryRows || []).map(row => Object.fromEntries(fields.map((field,i)=>[field,row[i]])));
    if (!rows.length) return null;
    const edible = rows.filter(row=>row.edibleStatus !== "waste" && row.preservationState !== "compost_or_disposal");
    const disposal = rows.filter(row=>row.edibleStatus === "waste" || row.preservationState === "compost_or_disposal");
    return `
      <div class="grid food-summary">
        ${metric(t("calories"),num(food.totalCaloriesReportedByGame,0),t("caloriesShort"))}
        ${metric(t("edible"),num(edible.reduce((n,r)=>n+Number(r.quantity||0),0)),`${edible.length} ${t("name").toLowerCase()}`)}
        ${metric(t("disposal"),num(disposal.reduce((n,r)=>n+Number(r.quantity||0),0)),`${disposal.length} ${t("name").toLowerCase()}`,"warn")}
      </div>
      <article class="card">
        <div class="toolbar"><input id="food-search" class="search" placeholder="${esc(t("search"))}"><select id="food-filter" class="filter"><option value="edible">${esc(t("edible"))}</option><option value="all">${esc(t("all"))}</option><option value="waste">${esc(t("disposal"))}</option></select></div>
        <div class="table-wrap"><table><thead><tr><th>${esc(t("name"))}</th><th>${esc(t("quantity"))}</th><th>${esc(t("freshness"))}</th><th>${esc(t("preservation"))}</th><th>${esc(t("calories"))}</th><th>${esc(t("location"))}</th></tr></thead><tbody id="food-body"></tbody></table></div>
      </article>`;
  }

  function fillFood() {
    const body=$("#food-body"); if(!body) return;
    const food=section("food"), fields=food.foodSummaryFields||[];
    const query=($("#food-search")?.value||"").toLowerCase(), filter=$("#food-filter")?.value||"edible";
    const rows=(food.foodSummaryRows||[]).map(row=>Object.fromEntries(fields.map((f,i)=>[f,row[i]]))).filter(row=>{
      const waste=row.edibleStatus==="waste"||row.preservationState==="compost_or_disposal";
      const matches=filter==="all"||(filter==="waste"?waste:!waste);
      return matches && `${row.name_ru} ${row.location_ru}`.toLowerCase().includes(query);
    });
    body.innerHTML=rows.map(r=>`<tr><td><strong>${esc(r.name_ru||r.fullType)}</strong></td><td class="qty">${num(r.quantity)}</td><td>${esc(r.freshness_ru||"—")}</td><td>${esc(r.preservationState||"—")}</td><td class="mono">${num(r.calories,1)}</td><td>${esc(r.location_ru||"—")}</td></tr>`).join("");
  }

  function renderResources() {
    if (!app.resources.length) return null;
    return `<article class="card">
      <div class="toolbar"><input id="resource-search" class="search" placeholder="${esc(t("search"))}"><select id="resource-filter" class="filter"><option value="all">${esc(t("all"))}</option><option value="duplicates">${esc(t("duplicates"))}</option></select></div>
      <div class="table-wrap"><table><thead><tr><th>${esc(t("name"))}</th><th>${esc(t("quantity"))}</th><th>${esc(t("onCharacter"))}</th><th>${esc(t("inBases"))}</th><th>${esc(t("inVehicles"))}</th><th>${esc(t("condition"))}</th><th>${esc(t("location"))}</th></tr></thead><tbody id="resources-body"></tbody></table></div>
    </article>`;
  }

  function fillResources() {
    const body=$("#resources-body"); if(!body) return;
    const query=($("#resource-search")?.value||"").toLowerCase(), filter=$("#resource-filter")?.value||"all";
    const rows=app.resources.filter(row=>(filter!=="duplicates"||Number(row.quantity)>1)&&`${row.name_ru} ${(row.locations||[]).join(" ")}`.toLowerCase().includes(query));
    body.innerHTML=rows.map(r=>`<tr><td><strong>${esc(r.name_ru||r.fullType)}</strong></td><td class="qty">${num(r.quantity)}</td><td>${num(r.onCharacter)}</td><td>${num(r.inBases)}</td><td>${num(r.inVehicles)}</td><td class="condition">${condition(r.conditionPercentMin)}</td><td>${(r.locations||[]).map(esc).join("<br>")}</td></tr>`).join("");
  }

  function renderHistory() {
    const value=section("changes"), rows=value.changes||value.events||value.recentChanges||[];
    if(!Array.isArray(rows)||!rows.length) return null;
    return `<article class="card"><div class="list">${rows.slice(0,100).map(row=>`<div class="list-row"><div><strong>${esc(row.message_ru||row.type||row.kind||t("updated"))}</strong><small class="mono">${esc(row.timestamp||row.at||row.item?.name_ru||"")}</small></div><span class="pill">${esc(row.quantity??row.delta??"")}</span></div>`).join("")}</div></article>`;
  }

  function render() {
    if(!app.data) return;
    $("#view-title").textContent=t("titles."+app.view);
    const status=get("bootstrap.status", {});
    $("#scan-time").textContent=status.lastScanAt ? new Date(status.lastScanAt).toLocaleString() : "—";
    $("#save-name").textContent=(status.activeSave||{}).name || "—";
    const view=$("#view");
    let html;
    if(app.view==="overview") html=renderOverview();
    if(app.view==="bases") html=renderBases();
    if(app.view==="vehicles") html=renderVehicles();
    if(app.view==="food") html=renderFood();
    if(app.view==="resources") html=renderResources();
    if(app.view==="history") html=renderHistory();
    if(!html) { view.replaceChildren(empty()); return; }
    view.innerHTML=html;
    if(app.view==="food") {
      fillFood();
      $("#food-search").addEventListener("input",fillFood);
      $("#food-filter").addEventListener("change",fillFood);
    }
    if(app.view==="resources") {
      fillResources();
      $("#resource-search").addEventListener("input",fillResources);
      $("#resource-filter").addEventListener("change",fillResources);
    }
  }

  async function loadPages(paths) {
    const pages=await Promise.all((paths||[]).map(path=>fetch("/api/v1/page/"+encodeURIComponent(baseName(path)),{cache:"no-store"}).then(r=>r.ok?r.json():null).catch(()=>null)));
    return pages.filter(Boolean);
  }

  async function loadDashboard() {
    const response=await fetch("/api/v1/dashboard",{cache:"no-store"});
    if(!response.ok) throw new Error("HTTP "+response.status);
    app.data=await response.json();
    const override=localStorage.getItem("pz-organizer-language");
    const automatic=get("language.selected","AUTO").toUpperCase();
    app.language=(override||(automatic==="AUTO"?browserLanguage():automatic)).toUpperCase();
    const resourcePages=get("sections.resources.summaryPages",[]);
    const pages=await loadPages(resourcePages);
    app.resources=pages.flatMap(page=>page.records||[]);
    setupLanguage();
    applyLanguage(app.language);
    const status=get("bootstrap.status",{});
    const ok=status.ok&&status.parsingSuccessful;
    setConnection(ok?"online":"offline",ok?t("online"):t("offline"));
    $("#notice").classList.toggle("hidden",ok);
    if(!ok) $("#notice").textContent=t("snapshotUnavailable");
  }

  async function poll() {
    try {
      const response=await fetch("/api/v1/health",{cache:"no-store"});
      if(!response.ok) throw new Error("health");
      const health=await response.json();
      const key=`${health.sequence}|${health.lastScanAt}|${health.saveId}`;
      if(app.healthKey!==key) {
        app.healthKey=key;
        await loadDashboard();
      }
    } catch (_) {
      setConnection("offline",t("offline"));
    }
  }

  $$("#nav .nav-item").forEach(button=>button.addEventListener("click",()=>{
    $$("#nav .nav-item").forEach(item=>item.classList.remove("active"));
    button.classList.add("active");
    app.view=button.dataset.view;
    render();
  }));

  poll();
  app.poll=setInterval(poll,2000);
})();
