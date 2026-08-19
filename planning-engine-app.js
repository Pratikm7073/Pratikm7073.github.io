"use strict";

/* Renders the page and wires the live capacity model.
   Chart helpers, the Erlang port and shared state live in the inline
   script in planning-engine.html. */

const app = document.getElementById("app");

function h(tag, attrs, html){
  const n = document.createElement(tag);
  for(const k in (attrs||{})){
    if(k === "class") n.className = attrs[k];
    else n.setAttribute(k, attrs[k]);
  }
  if(html != null) n.innerHTML = html;
  return n;
}
function kpi(label, value, detail, mod){
  return `<div class="kpi ${mod||""}"><div class="k">${label}</div>
    <div class="v">${value}</div>${detail?`<div class="d">${detail}</div>`:""}</div>`;
}
function section(num, title, sub, bodyHtml){
  return `<section><h2><span class="n">${num}</span>${title}</h2>
    <p class="sub">${sub}</p>${bodyHtml}</section>`;
}

/* ── Header and headline ─────────────────────────────────────────── */
function renderHeader(){
  const m = DATA.meta, hd = DATA.headline, cfg = DATA.config;
  const short = hd.weeks_short;
  return `
  <header><div class="wrap">
    <div class="eyebrow">Workforce Planning · Multi-channel Contact Centre</div>
    <h1>Retail Resource Planning &amp; Forecast Engine</h1>
    <p class="lede">Demand forecasting and capacity planning for a water retailer's contact
      operation — five channels, sixteen service lines, a 24/7 operational queue and a
      small Welsh-language skill pool. Forecasts contacts, sizes every half hour with
      queueing theory, models advisor supply against attrition and the training pipeline,
      then prices the gap and says what to do about it.</p>
    <div class="disclaimer"><span>⚠</span><span><b>All data on this page is synthetic.</b>
      ${m.dataNote} The engine is built to a documented CSV schema so a real extract drops
      straight in; the structure is faithful, the numbers are invented.</span></div>
    <div class="links">
      <a class="primary" href="https://github.com/Pratikm7073/Pratikm7073.github.io/tree/main/planning-engine">Source &amp; README ↗</a>
      <a href="https://github.com/Pratikm7073/Pratikm7073.github.io/tree/main/planning-engine/tests">Test suite ↗</a>
      <a href="/">← Back to portfolio</a>
    </div>
  </div></header>

  <div class="wrap">
  ${section("01", "The plan in one screen",
    `Horizon ${dmyy(m.horizonStart)} to ${dmyy(m.horizonEnd)} — ${m.weeks} weeks, forecast at
     service-line level and rolled up. Every figure below is produced by the engine, not typed in.`,
    `<div class="kpis">
      ${kpi("Contacts forecast", (hd.total_contacts/1e6).toFixed(2)+"m", `across ${DATA.accuracy.length} service lines`)}
      ${kpi("Mean FTE required", fmt(hd.mean_required_fte,1), "rostered, after shrinkage")}
      ${kpi("Peak FTE required", fmt(hd.peak_required_fte,1), "w/c "+dmy(hd.peak_week))}
      ${kpi("Weeks below cover", short, `of ${m.weeks} weeks`, short>0?"warn":"ok")}
      ${kpi("Worst weekly gap", fmt(hd.worst_gap_fte,1)+" FTE", "supply minus requirement", "warn")}
      ${kpi("Resourcing cost", gbpK(hd.total_cost), "over the horizon")}
      ${kpi("Premium cost", gbpK(hd.premium_cost), "overtime + agency")}
      ${kpi("Idle capacity", fmt(hd.idle_fte_weeks,0), "FTE-weeks paid with no demand", "warn")}
    </div>`)}
  </div>`;
}

/* ── Demand ──────────────────────────────────────────────────────── */
function renderDemand(){
  const wrap = h("div", {class:"wrap"});
  wrap.innerHTML = section("02", "Demand: history and forecast",
    `Weekly contacts across all channels. The February spike is the annual charges
     notification working through the billing queues; the winter lift on the operational
     lines is freeze–thaw. Both are modelled as named calendar events rather than left for
     the seasonality to absorb, which is why the forecast reproduces them instead of
     smoothing them away.`,
    `<div class="panel"><div class="chart-wrap" id="c-demand"></div>
      <div class="legend">
        <span><i style="background:var(--ink-3)"></i>Actual history</span>
        <span><i style="background:var(--brand)"></i>Forecast</span>
      </div></div>`);
  wrap.querySelector("#c-demand").appendChild(chartDemand());
  return wrap;
}

/* ── Supply vs demand ────────────────────────────────────────────── */
function renderPlan(){
  const wrap = h("div", {class:"wrap"});
  const rows = DATA.weekly.map(w => {
    const g = w.gap_fte;
    return `<tr>
      <td class="mono">${dmy(w.week_start)}</td>
      <td class="num">${fmt(w.contacts)}</td>
      <td class="num">${fmt(w.required_fte,1)}</td>
      <td class="num">${fmt(w.supply_fte,1)}</td>
      <td class="num ${g<-0.5?"neg":(g>0.5?"pos":"")}">${g>0?"+":""}${fmt(g,1)}</td>
      <td class="num">${w.intake||""}</td>
      <td class="num">${w.overtime_hours>1?fmt(w.overtime_hours):""}</td>
      <td class="num">${w.agency_hours>1?fmt(w.agency_hours):""}</td>
      <td class="num">${gbpK(w.total_cost)}</td></tr>`;
  }).join("");

  wrap.innerHTML = section("03", "Requirement against supply",
    `Supply is not a constant. Attrition erodes it every week, and recruits are not capacity
     until they clear ${DATA.config.supply.trainingWeeks} weeks of training and
     ${DATA.config.supply.nestingWeeks} of nesting — a
     <b>${DATA.config.supply.pipelineWeeks}-week pipeline</b> from decision to productive advisor.
     Shaded red is a shortfall, green a surplus.`,
    `<div class="panel"><div class="chart-wrap" id="c-plan"></div>
      <div class="legend">
        <span><i style="background:var(--brand)"></i>FTE required</span>
        <span><i style="background:var(--brand-2)"></i>FTE supplied</span>
        <span><i style="background:var(--bad);opacity:.5"></i>Shortfall</span>
        <span><i style="background:var(--good);opacity:.5"></i>Surplus</span>
      </div></div>
     <div class="tw" style="margin-top:1.1rem"><table>
      <thead><tr><th>Week</th><th class="num">Contacts</th><th class="num">Required</th>
      <th class="num">Supply</th><th class="num">Gap</th><th class="num">Intake</th>
      <th class="num">OT hrs</th><th class="num">Agency hrs</th><th class="num">Cost</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`);
  wrap.querySelector("#c-plan").appendChild(chartSupplyDemand());
  return wrap;
}

/* ── The live model ──────────────────────────────────────────────── */
const CONTROLS = [
  {key:"volume",    label:"Contact volume",        min:0.7,  max:1.4,  step:0.01, fmt:v=>(v>=1?"+":"")+((v-1)*100).toFixed(0)+"%"},
  {key:"aht",       label:"Average handle time",   min:0.7,  max:1.4,  step:0.01, fmt:v=>(v>=1?"+":"")+((v-1)*100).toFixed(0)+"%"},
  {key:"slTarget",  label:"Service level target",  min:0.60, max:0.98, step:0.01, fmt:v=>(v*100).toFixed(0)+"%"},
  {key:"slSecs",    label:"…answered within",      min:5,    max:90,   step:5,    fmt:v=>v+"s"},
  {key:"shrinkage", label:"Shrinkage",             min:0.10, max:0.45, step:0.005,fmt:v=>(v*100).toFixed(1)+"%"},
  {key:"occupancy", label:"Max occupancy",         min:0.70, max:0.98, step:0.01, fmt:v=>(v*100).toFixed(0)+"%"}
];

function renderModel(){
  const wrap = h("div", {class:"wrap"});
  const controls = CONTROLS.map(c => `
    <div class="ctrl">
      <label for="s-${c.key}">${c.label} <b id="v-${c.key}"></b></label>
      <input type="range" id="s-${c.key}" min="${c.min}" max="${c.max}" step="${c.step}">
    </div>`).join("");

  wrap.innerHTML = section("04", "Live capacity model",
    `This is the same Erlang C, shrinkage and cost calculation the Python engine runs,
     ported to the browser and re-run on every input. Move a slider and the half-hourly
     requirement for ${dmyy(DATA.meta.sampleDay)} is resized from scratch — nothing here is
     precomputed. Watch what a <b>+10% volume</b> move does to headcount — it lands
     <b>under 10%</b>, because larger queues pool their variance better. The effect is
     diluted here because the deferrable channels scale linearly by construction; on the
     voice queues alone it is stronger. That non-linearity is why scenarios have to be
     re-run rather than scaled.`,
    `<div class="grid-controls">
      <div class="panel">
        <div style="font-size:.78rem;font-family:'Geist Mono',monospace;color:var(--ink-3);
          text-transform:uppercase;letter-spacing:.05em;margin-bottom:1rem">Assumptions</div>
        ${controls}
        <button class="reset" id="reset">↺ Reset to plan assumptions</button>
      </div>
      <div>
        <div class="kpis" id="live-kpis" style="margin-bottom:1rem"></div>
        <div class="panel"><div class="chart-wrap" id="c-intraday"></div>
          <div class="legend">
            <span><i style="background:var(--brand)"></i>Rostered (after shrinkage)</span>
            <span><i style="background:var(--brand-2)"></i>On the phone</span>
          </div></div>
      </div>
    </div>`);
  return wrap;
}

function refreshModel(){
  CONTROLS.forEach(c => {
    document.getElementById("s-"+c.key).value = S[c.key];
    document.getElementById("v-"+c.key).textContent = c.fmt(S[c.key]);
  });

  const sized = sizeDay();
  const base = BASELINE;
  const dPeak = sized.peak - base.peak;
  const dCost = sized.dayCost - base.dayCost;
  const slMod = sized.achievedSl < S.slTarget - 0.005 ? "warn" : "ok";
  const occMod = sized.occupancy > S.occupancy + 0.005 ? "warn" : "";

  document.getElementById("live-kpis").innerHTML =
      kpi("Peak rostered", fmt(sized.peak,1)+" FTE",
          (dPeak>=0?"+":"")+fmt(dPeak,1)+" vs plan", Math.abs(dPeak)<0.05?"":(dPeak>0?"warn":"ok"))
    + kpi("Rostered hours", fmt(sized.rosteredHours,0), "for the day")
    + kpi("Day cost", gbp(sized.dayCost), (dCost>=0?"+":"")+gbp(dCost)+" vs plan",
          Math.abs(dCost)<1?"":(dCost>0?"warn":"ok"))
    + kpi("Service level", pct(sized.achievedSl,1), "delivered at this staffing", slMod)
    + kpi("Occupancy", pct(sized.occupancy,1), "weighted, interactive only", occMod)
    + kpi("Contacts", fmt(sized.totalContacts,0), "on the sample day");

  const host = document.getElementById("c-intraday");
  host.innerHTML = "";
  host.appendChild(chartIntraday(sized));
}

/* ── Shrinkage ───────────────────────────────────────────────────── */
function renderShrinkage(){
  const sh = DATA.config.shrinkage;
  const naive = Object.values(sh.components).reduce((a,b)=>a+b,0);
  const per100 = 100/(1-sh.total) - 100*(1+naive);
  const wrap = h("div", {class:"wrap"});
  wrap.innerHTML = section("05", "Shrinkage, compounded",
    `Shrinkage components do not add — they compound. Regular shrinkage (leave, training,
     coaching, breaks) and irregular shrinkage (sickness, system downtime) combine as
     <code>1 − (1−r)(1−i)</code>. And the requirement is grossed up by
     <b>dividing</b> by (1 − shrinkage), never by multiplying by (1 + shrinkage): at
     ${pct(sh.total,1)} those two give ${fmt(100/(1-sh.total),1)} and ${fmt(100*(1+sh.total),1)}
     FTE per 100 on the phone. The multiply error under-staffs, invisibly, every time.`,
    `<div class="grid2">
      <div class="panel"><div class="chart-wrap" id="c-shrink"></div></div>
      <div class="panel">
        <div class="kpis" style="grid-template-columns:1fr 1fr">
          ${kpi("Regular", pct(sh.regular,1), "planned, rostered")}
          ${kpi("Irregular", pct(sh.irregular,1), "unplanned")}
          ${kpi("Total (compounded)", pct(sh.total,1), "the correct figure", "ok")}
          ${kpi("Uplift factor", "×"+fmt(sh.upliftFactor,3), "rostered ÷ on phone")}
        </div>
        <p style="font-size:.86rem;color:var(--ink-2);margin-top:1rem">
          Per 100 advisors needed on the phone, the correct build-up rosters
          <b>${fmt(100/(1-sh.total),1)}</b> FTE. Treating shrinkage as a simple sum and
          multiplying would roster ${fmt(100*(1+naive),1)} —
          <b>${fmt(Math.abs(per100),1)} FTE short</b>, before anyone has taken a call.</p>
      </div>
    </div>`);
  wrap.querySelector("#c-shrink").appendChild(chartShrinkage());
  return wrap;
}

/* ── Accuracy ────────────────────────────────────────────────────── */
function renderAccuracy(){
  const rows = DATA.accuracy;
  const meanImp = rows.reduce((a,r)=>a+r.improvementPct,0)/rows.length;
  const meanBase = rows.reduce((a,r)=>a+r.baselineWape,0)/rows.length;
  const meanChosen = rows.reduce((a,r)=>a+r.chosenWape,0)/rows.length;
  const wrap = h("div", {class:"wrap"});
  wrap.innerHTML = section("06", "Does the forecast actually work?",
    `Measured by rolling-origin backtest: the model is re-fitted at successive cut-off dates
     and scored only against data it could not see, pooled across every origin. The baseline
     is a seasonal naive forecast — the median of the last four same-weekdays. Quoting
     accuracy without a baseline is how forecasting projects get oversold, so the baseline is
     always on the chart. <b>WAPE</b> weights by volume; MAPE would let a sixty-contact
     Welsh-language Sunday count as heavily as a four-thousand-call Monday.`,
    `<div class="kpis" style="margin-bottom:1.1rem">
      ${kpi("Baseline WAPE", fmt(meanBase,1)+"%", "seasonal naive, mean of 16 lines")}
      ${kpi("Engine WAPE", fmt(meanChosen,1)+"%", "selected model per line", "ok")}
      ${kpi("Error reduction", fmt(meanImp,1)+"%", "mean across service lines", "ok")}
      ${kpi("Lines beating baseline", rows.filter(r=>r.chosenWape<r.baselineWape).length+" / "+rows.length, "at the short-term horizon", "ok")}
     </div>
     <div class="panel"><div class="chart-wrap" id="c-acc"></div>
      <div class="legend">
        <span><i style="background:var(--ink-3);opacity:.6"></i>Seasonal naive baseline</span>
        <span><i style="background:var(--brand)"></i>Selected model</span>
        <span style="color:var(--ink-3)">Right-hand figure is the error reduction</span>
      </div></div>`);
  wrap.querySelector("#c-acc").appendChild(chartAccuracy());
  return wrap;
}

/* ── Scenarios ───────────────────────────────────────────────────── */
function renderScenarios(){
  const rows = DATA.scenarios.map(s => `<tr>
    <td><b>${s.label}</b></td>
    <td class="num">${fmt(s.mean_required_fte,1)}</td>
    <td class="num ${s.fte_vs_base>0?"neg":(s.fte_vs_base<0?"pos":"")}">${s.fte_vs_base>0?"+":""}${fmt(s.fte_vs_base,1)}</td>
    <td class="num">${s.weeks_short}</td>
    <td class="num">${fmt(s.idle_fte_weeks,0)}</td>
    <td class="num">${gbpK(s.premium_cost)}</td>
    <td class="num">${gbpK(s.total_cost)}</td>
    <td class="num ${s.cost_vs_base_pct>0?"neg":(s.cost_vs_base_pct<0?"pos":"")}">${s.cost_vs_base_pct>0?"+":""}${fmt(s.cost_vs_base_pct,2)}%</td>
  </tr>`).join("");

  const wrap = h("div", {class:"wrap"});
  wrap.innerHTML = section("07", "Scenarios — re-run, not scaled",
    `Each row re-runs the full half-hourly sizing across the whole horizon. Two results worth
     pausing on. <b>Volume +10% needs under 10% more headcount</b>, because Erlang
     staffing grows roughly as load plus a term in its square root. And <b>higher attrition
     shows as marginally cheaper in cash</b> — not because losing people is good, but because
     this plan already carries ${fmt(DATA.headline.idle_fte_weeks,0)} FTE-weeks of idle
     capacity, so attrition eats surplus before it eats service. The weeks-short and premium
     columns are where the real damage shows.`,
    `<div class="tw"><table>
      <thead><tr><th>Scenario</th><th class="num">Mean FTE</th><th class="num">Δ FTE</th>
      <th class="num">Weeks short</th><th class="num">Idle FTE-wks</th>
      <th class="num">Premium</th><th class="num">Total cost</th><th class="num">Δ cost</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`);
  return wrap;
}

/* ── Risks ───────────────────────────────────────────────────────── */
function renderRisks(){
  const cards = DATA.risks.map(r => `
    <div class="risk ${r.severity}">
      <div class="rh"><div class="rt">${r.title}</div><div class="sev">${r.severity}</div></div>
      <div style="font-size:.85rem;color:var(--ink-2)">${r.detail}</div>
      <div class="tagrow">
        ${r.week?`<span class="tag">w/c ${dmy(r.week)}</span>`:`<span class="tag">horizon-wide</span>`}
        <span class="tag">${r.recoverable==="Yes"?"recruitable":"inside lead time"}</span>
        ${r.impact_fte?`<span class="tag">${fmt(r.impact_fte,0)} FTE</span>`:""}
        ${r.estimated_saving?`<span class="tag">saving ${gbpK(r.estimated_saving)}</span>`:""}
      </div>
      <div class="rm"><b>Mitigation.</b> ${r.mitigation}</div>
    </div>`).join("");

  const wrap = h("div", {class:"wrap"});
  wrap.innerHTML = section("08", "Early-warning register",
    `A gap in week 21 is not news in week 21 — it is news now, while there is still time to
     act, and only if it arrives with a costed option attached. The test that changes
     behaviour is <b>recoverability</b>: a shortfall inside the
     ${DATA.config.supply.pipelineWeeks}-week recruitment pipeline cannot be hired for at any
     price, so raising it as "we need to recruit" is useless advice. Those entries get leave
     re-profiling, overtime and deflection instead.`,
    `<div class="risks">${cards}</div>`);
  return wrap;
}

/* ── Method ──────────────────────────────────────────────────────── */
function renderMethod(){
  const wrap = h("div", {class:"wrap"});
  wrap.innerHTML = section("09", "Method, and what it does not do",
    "The parts worth defending, and the limits worth stating before anyone else finds them.",
    `<div class="notes">
      <h3>Forecasting</h3>
      <p>Three models compete per service line: a <strong>seasonal naive baseline</strong>, a
        <strong>multiplicative decomposition</strong> (the transparent method a good Excel
        model uses — weekday index, annual index, named event uplifts, damped trend), and a
        <strong>ridge regression on log volume</strong> over a calendar and event design
        matrix. Selection is by rolling-origin backtest at the short-term horizon, because
        that is where overtime is committed and shifts are locked.</p>
      <p>The regression is fitted in two passes. Pass one tests for a
        <strong>structural break</strong> — a permanent level shift such as a self-serve
        portal launch — by refitting at candidate dates and scoring on BIC. Pass two flags
        what the fitted model still cannot explain and refits without it. Both detectors run
        on residuals or on refits, never on raw volume: scanning raw volume for a level shift
        finds one in every series, because annual seasonality guarantees some split separates
        a busy half from a quiet half.</p>
      <h3>Capacity</h3>
      <p><strong>Erlang C</strong> sizes interactive channels; deferrable channels use a
        workload calculation against their SLA, because an email answered in six hours is as
        compliant as one answered in six minutes. <strong>Erlang A</strong> is implemented
        too, exactly, from the birth–death chain. Across a representative volume range it
        asks for <strong>718 advisors where Erlang C asks for 858</strong> — Erlang C wants
        <strong>19.5% more</strong> to hold a 5% abandonment target, because it assumes
        nobody ever hangs up and so sizes for a queue that in reality partly clears
        itself.</p>
      <p>Shift covering is a greedy set-cover scored on useful hours per paid hour, capped at
        a recruitable part-time mix. Left to optimise freely it covers a double-humped curve
        almost entirely with four-hour shifts: genuinely the cheapest roster, and one nobody
        can hire for.</p>
      <h3>Limitations — stated up front</h3>
      <ul>
        <li><strong>The data is synthetic.</strong> Accuracy figures describe this engine on
          this generator, not a claim about any real operation. The generator shares no
          seasonal code with the estimator, so the backtest is not circular, but it is still
          a simulation.</li>
        <li><strong>The long-term horizon is not validated.</strong> Testing a 24-month
          forecast needs more than 24 months of history to test against. The engine will
          produce one; the accuracy section deliberately does not score it.</li>
        <li><strong>Chat concurrency is an approximation.</strong> An advisor holding 2.2
          conversations is modelled as 2.2 servers, which is slightly optimistic — real
          concurrency lengthens handle time as it rises.</li>
        <li><strong>One changepoint, not many.</strong> Two years of daily history cannot
          support a multi-changepoint search without over-fitting.</li>
        <li><strong>Models under-forecast into sharp peaks.</strong> Visible in the bias
          column and it is the direction that hurts service, which is why peak weeks carry a
          risk buffer rather than a point estimate.</li>
      </ul>
     </div>
     <footer>Built in Python (numpy · pandas · openpyxl) with a browser demo in vanilla JS and
      raw SVG — no charting library, no build step. ${DATA.accuracy.length} service lines ·
      5 channels · 130 unit tests. Generated ${dmyy(DATA.meta.generated)}.
      <a href="https://github.com/Pratikm7073/Pratikm7073.github.io/tree/main/planning-engine">View the source ↗</a>
     </footer>`);
  return wrap;
}

/* ── Boot ────────────────────────────────────────────────────────── */
let BASELINE = null;

function render(){
  app.innerHTML = renderHeader();
  [renderDemand(), renderPlan(), renderModel(), renderShrinkage(),
   renderAccuracy(), renderScenarios(), renderRisks(), renderMethod()]
    .forEach(node => app.appendChild(node));

  CONTROLS.forEach(c => {
    const input = document.getElementById("s-"+c.key);
    input.addEventListener("input", () => {
      S[c.key] = parseFloat(input.value);
      refreshModel();
    });
  });
  document.getElementById("reset").addEventListener("click", () => {
    resetState();
    refreshModel();
  });
  refreshModel();
}

fetch("planning-engine-data.json")
  .then(r => { if(!r.ok) throw new Error("HTTP "+r.status); return r.json(); })
  .then(json => {
    DATA = json;
    resetState();
    BASELINE = sizeDay();      /* reference point for the "vs plan" deltas */
    render();
  })
  .catch(err => {
    app.innerHTML = `<div class="wrap" style="padding-top:4rem"><div class="err">
      <b>Could not load planning-engine-data.json.</b><br>
      ${err.message}. This page reads its data over <code>fetch</code>, which browsers block
      on <code>file://</code> — serve the folder over HTTP
      (<code>python3 -m http.server</code>) or view it on GitHub Pages.
    </div></div>`;
  });
