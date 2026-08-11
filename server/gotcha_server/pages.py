"""Backend-served web pages (D31, §9.1) -- Phase 5.

The player-facing pages a phone browser opens (the badge's QR points here) plus
the host admin console. Three pages:

  * `/gotcha/`     -- the player card (§9.1): public stats + token-gated target,
                      the four leaderboards, and the hit list. The QR flow
                      (0.11.24) encodes `…/gotcha/?badge=<pid>&t=<token>`.
  * `/klassement`  -- the standalone public standings: the four boards and the
                      hit list, full-width. This is the "leaderboards" deliverable
                      browsable without scanning a QR -- the thing you project on
                      a camp screen or check between kills.
  * `/admin`       -- the host dashboard (§9.4), the screen a host needs on a
                      phone the moment badges are handed out.

Everything is inline HTML/CSS/JS on purpose: one process, no build step, no CDN,
no asset pipeline to break on a laptop in a field with the uplink down. Same
origin as the API, so the pages read the unsigned `/v1/public/*` views (D21
governs the *badge* path only; these publish only what the boards publish anyway).

Player-facing text is Dutch (D26). ASCII only, as elsewhere in this project.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import clock, crypto, service

router = APIRouter()

STYLE = """
:root { color-scheme: dark light; }
* { box-sizing: border-box; }
body { margin: 0; font: 16px/1.45 system-ui, -apple-system, sans-serif;
       background: #12141a; color: #e8e8ea; }
a { color: #7fb2ff; }
header { padding: 14px 16px; background: #1b1e27; border-bottom: 1px solid #2b2f3a;
         display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
header h1 { font-size: 18px; margin: 0; }
header .sub { color: #9aa0ae; font-size: 13px; }
main { padding: 16px; max-width: 900px; margin: 0 auto; }
.card { background: #1b1e27; border: 1px solid #2b2f3a; border-radius: 10px;
        padding: 14px; margin-bottom: 14px; }
.card h2 { font-size: 14px; text-transform: uppercase; letter-spacing: .08em;
           color: #9aa0ae; margin: 0 0 10px; }
.big { font-size: 68px; line-height: 1; font-weight: 700; }
.big.warn { color: #ffb03a; }
.big.bad { color: #ff5d5d; }
.grid { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); }
.stat { background: #22263180; border-radius: 8px; padding: 10px; }
.stat .n { font-size: 24px; font-weight: 600; }
.stat .l { font-size: 12px; color: #9aa0ae; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 5px 6px; border-bottom: 1px solid #2b2f3a; }
th { color: #9aa0ae; font-weight: 500; font-size: 12px; }
button, input, select { font: inherit; padding: 8px 10px; border-radius: 8px;
        border: 1px solid #39405060; background: #262b36; color: #e8e8ea; }
button { cursor: pointer; background: #2f6fd0; border-color: #2f6fd0; }
button.ghost { background: #262b36; border-color: #394050; }
button.danger { background: #b03636; border-color: #b03636; }
.row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.pill { display: inline-block; padding: 2px 8px; border-radius: 999px;
        background: #2f3644; font-size: 12px; }
.pill.on { background: #2f6fd0; }
.pill.warn { background: #8a5a12; }
.muted { color: #9aa0ae; }
footer { padding: 20px 16px; color: #6d7280; font-size: 12px; text-align: center; }
"""


def html_escape(s):
    """Minimal escaping for the one place a user-supplied string (the host's own
    name, typed at login) is interpolated into a page."""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def page(title, body, extra_head=""):
    return HTMLResponse(
        "<!doctype html><html lang=\"nl\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>%s</title><style>%s</style>%s</head><body>%s</body></html>"
        % (title, STYLE, extra_head, body))


@router.get("/")
async def root():
    return RedirectResponse("/gotcha/")


# ---------------------------------------------------------------------------
# Public standings (§9.1 leaderboards) -- browse without a QR
# ---------------------------------------------------------------------------

@router.get("/klassement")
async def standings():
    """The standalone public leaderboard page: the four boards and the hit list,
    full-width, auto-refreshing. Reachable without scanning a QR (unlike the
    player card), so it is the page to project on a camp screen or check between
    kills. Public data only -- exactly what the boards publish."""
    body = """
<header><h1>!Fri3d Friends &mdash; Klassement</h1>
  <span class="sub" id="clock">laden...</span>
  <span class="sub"><a href="/gotcha/">mijn kaart</a></span></header>
<main>
  <div class="card"><h2>Prijzenlijst</h2><div id="hitlist" class="muted">laden...</div></div>
  <div class="card"><h2>Klassement</h2>
    <div class="row" id="tabs" style="margin-bottom:10px"></div>
    <div id="boardbody"></div>
  </div>
</main>
<footer>Alles wat je hier ziet is openbaar. Wie wie uitschakelt staat op het
  klassement &mdash; dat is met opzet.</footer>
<script>
const TABS = [
  ['total',            'Totaal (punten)'],
  ['streak',           'Langste reeks'],
  ['group_total',      'Groepen: totaal'],
  ['group_per_member', 'Groepen: per lid'],
];
let board = 'total';
async function j(u){ const r = await fetch(u); if(!r.ok) throw new Error(r.status); return r.json(); }
function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function renderTabs(){
  document.getElementById('tabs').innerHTML = TABS.map(([k,lbl])=>
    '<button class="' + (k===board?'':'ghost') + '" onclick="pick(\''+k+'\')">' + lbl + '</button>').join('');
}
function pick(b){ board = b; renderTabs(); loadBoard(); }
async function loadBoard(){
  const d = await j('/v1/public/leaderboard?board=' + board + '&limit=50');
  const grp = board.startsWith('group');
  const head = grp
    ? '<tr><th>#</th><th>groep</th><th>' + (board==='group_per_member'?'per lid':'punten') + '</th><th>leden</th></tr>'
    : '<tr><th>#</th><th>speler</th><th>' + (board==='streak'?'beste reeks':'punten') + '</th><th>kills</th></tr>';
  const rows = d.entries.map((e,i)=>{
    if(grp) return '<tr><td>'+(i+1)+'</td><td>'+esc(e.name)+'</td><td>'+
      (board==='group_per_member'? e.per_member : e.points)+'</td><td class="muted">'+e.members+'</td></tr>';
    const v = board==='streak' ? e.best_streak : e.score;
    return '<tr><td>'+(i+1)+'</td><td>'+esc(e.name)+' #'+e.pid+'</td><td>'+v+'</td><td class="muted">'+e.kills+' kills</td></tr>';
  }).join('');
  document.getElementById('boardbody').innerHTML =
    '<table>' + head + (rows || '<tr><td colspan="4" class="muted">nog geen scores</td></tr>') + '</table>';
}
async function loadHitlist(){
  const d = await j('/v1/public/hitlist');
  document.getElementById('hitlist').innerHTML = d.hitlist.length
    ? d.hitlist.map(h=>'<span class="pill warn">'+esc(h.name)+' #'+h.pid+' &middot; reeks '+h.streak+'</span>').join(' ')
    : 'Niemand heeft nu een prijs op zijn hoofd.';
}
async function tickClock(){
  try { const d = await j('/healthz');
    document.getElementById('clock').textContent = new Date(d.server_time*1000).toLocaleTimeString('nl-BE');
  } catch(e) { document.getElementById('clock').textContent = 'GEEN VERBINDING'; }
}
renderTabs(); loadBoard(); loadHitlist(); tickClock();
setInterval(()=>{ loadBoard(); loadHitlist(); tickClock(); }, 30000);
</script>
"""
    return page("Klassement &mdash; !Fri3d Friends", body)


# ---------------------------------------------------------------------------
# Player card (§9.1) -- public by default, private view with a read token
# ---------------------------------------------------------------------------

@router.get("/gotcha/")
async def player_card(request: Request):
    """The page the badge's QR points at: `/gotcha/?badge=<pid>&t=<token>`.

    Without a token it shows public data only (score, streak, boards). With a
    valid token it also shows your target -- which is the whole point, and why
    the token is short-lived and rides the sync response rather than living in
    the URL forever.
    """
    body = """
<header><h1>!Fri3d Friends &mdash; Gotcha</h1>
  <span class="sub" id="sub">laden...</span>
  <span class="sub"><a href="/klassement">klassement</a></span></header>
<main>
  <div class="card" id="me"><h2>Speler</h2><div class="muted">Scan de QR-code op je
    badge om je eigen kaart te zien.</div></div>
  <div class="card" id="target" hidden><h2>Jouw doelwit</h2><div id="targetbody"></div></div>
  <div class="card"><h2>Klassement</h2>
    <div class="row">
      <select id="board">
        <option value="total">Totaal (punten)</option>
        <option value="streak">Langste reeks</option>
        <option value="group_total">Groepen: totaal</option>
        <option value="group_per_member">Groepen: per lid</option>
      </select>
    </div>
    <div id="boardbody" style="margin-top:10px"></div>
  </div>
  <div class="card"><h2>Prijzenlijst</h2><div id="hitlist" class="muted">laden...</div></div>
</main>
<footer>Alles wat je hier ziet is openbaar. Wie wie uitschakelt staat op het
  klassement &mdash; dat is met opzet.</footer>
<script>
const qs = new URLSearchParams(location.search);
const pid = qs.get('badge'), tok = qs.get('t');
async function j(u){ const r = await fetch(u); if(!r.ok) throw new Error(r.status); return r.json(); }
function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
async function loadMe(){
  if(!pid) return;
  try{
    const u = '/v1/public/player/' + encodeURIComponent(pid) + (tok ? '?t=' + encodeURIComponent(tok) : '');
    const d = await j(u);
    document.getElementById('sub').textContent = d.name + ' #' + d.pid;
    document.getElementById('me').innerHTML =
      '<h2>' + esc(d.name) + ' #' + d.pid + '</h2><div class="grid">' +
      ['<div class="stat"><div class="n">' + d.score + '</div><div class="l">punten</div></div>',
       '<div class="stat"><div class="n">' + d.kills + '</div><div class="l">kills</div></div>',
       '<div class="stat"><div class="n">' + d.streak + '</div><div class="l">reeks nu</div></div>',
       '<div class="stat"><div class="n">' + d.best_streak + '</div><div class="l">beste reeks</div></div>',
       '<div class="stat"><div class="n">' + d.deaths + '</div><div class="l">keer uit</div></div>',
       '<div class="stat"><div class="n">' + (d.rank_total||'-') + '</div><div class="l">plaats</div></div>'
      ].join('') + '</div><div class="row" style="margin-top:10px"><span class="pill' +
      (d.status==='active'?' on':'') + '">' + esc(d.status_nl) + '</span>' +
      (d.groups||[]).map(g=>'<span class="pill">'+esc(g)+'</span>').join('') + '</div>';
    if(d.target){
      document.getElementById('target').hidden = false;
      document.getElementById('targetbody').innerHTML =
        '<div class="big" style="font-size:32px">' + esc(d.target.name) + ' #' + d.target.pid + '</div>' +
        '<div class="muted">laatst gezien: ' + Math.round(d.target.last_seen_ago_s/60) + ' min geleden</div>';
    }
  }catch(e){ document.getElementById('sub').textContent = 'speler niet gevonden'; }
}
async function loadBoard(){
  const b = document.getElementById('board').value;
  const d = await j('/v1/public/leaderboard?board=' + b + '&limit=25');
  const rows = d.entries.map((e,i)=>{
    if(b.startsWith('group')) return '<tr><td>'+(i+1)+'</td><td>'+esc(e.name)+'</td><td>'+
      (b==='group_per_member'? e.per_member : e.points)+'</td><td class="muted">'+e.members+' leden</td></tr>';
    const v = b==='streak' ? e.best_streak : e.score;
    return '<tr><td>'+(i+1)+'</td><td>'+esc(e.name)+' #'+e.pid+'</td><td>'+v+'</td><td class="muted">'+e.kills+' kills</td></tr>';
  }).join('');
  document.getElementById('boardbody').innerHTML = '<table><tr><th>#</th><th>naam</th><th>score</th><th></th></tr>'+rows+'</table>';
}
async function loadHitlist(){
  const d = await j('/v1/public/hitlist');
  document.getElementById('hitlist').innerHTML = d.hitlist.length
    ? d.hitlist.map(h=>'<span class="pill warn">'+esc(h.name)+' #'+h.pid+' &middot; reeks '+h.streak+'</span>').join(' ')
    : 'Niemand heeft nu een prijs op zijn hoofd.';
}
document.getElementById('board').addEventListener('change', loadBoard);
loadMe(); loadBoard(); loadHitlist();
setInterval(()=>{ loadBoard(); loadHitlist(); }, 30000);
</script>
"""
    return page("Gotcha &mdash; !Fri3d Friends", body)


# ---------------------------------------------------------------------------
# Admin dashboard (§9.4) -- the screen, not the endpoints
# ---------------------------------------------------------------------------

@router.get("/admin")
async def admin_page(request: Request):
    host = crypto.session_host(request.app.state.secret,
                               request.cookies.get("gotcha_admin", ""), clock.now())
    if not host:
        return page("Gotcha admin", """
<header><h1>Gotcha &mdash; host login</h1></header>
<main><div class="card"><h2>Aanmelden</h2>
  <form method="post" action="/admin/login">
    <div class="row" style="margin-bottom:10px">
      <input name="host" placeholder="jouw naam (bv. Ward)" required>
      <input name="password" type="password" placeholder="wachtwoord" required>
      <button type="submit">Aanmelden</button>
    </div>
  </form>
  <div class="muted">Je naam komt in het actielogboek te staan &mdash; meerdere
  hosts kunnen gelijktijdig aangemeld zijn.</div>
</div></main>""")

    db = request.app.state.db
    game = service.current_game(db)
    body = """
<header><h1>Gotcha dashboard</h1>
  <span class="sub">host: __HOST__ &middot; <a href="#" onclick="logout()">afmelden</a></span>
  <span class="sub" id="clock"></span></header>
<main>
  <div class="card">
    <h2>Kills laatste 10 minuten</h2>
    <div class="big" id="k10">-</div>
    <div class="muted">Dit is het enige getal dat "het spel loopt rustig"
      onderscheidt van "het spel is stil gestopt". Blijft dit lang 0 terwijl er
      spelers wakker zijn: ga kijken.</div>
    <div class="grid" style="margin-top:12px">
      <div class="stat"><div class="n" id="k1h">-</div><div class="l">kills laatste uur</div></div>
      <div class="stat"><div class="n" id="ktot">-</div><div class="l">kills totaal</div></div>
      <div class="stat"><div class="n" id="rev10">-</div><div class="l">reveals 10 min</div></div>
    </div>
  </div>

  <div class="card"><h2>Spelers</h2><div class="grid" id="pop"></div></div>
  <div class="card"><h2>Gezondheid</h2><div class="grid" id="health"></div></div>
  <div class="card"><h2>Vloot</h2><div class="grid" id="fleet"></div>
    <div id="versions" style="margin-top:10px"></div></div>

  <div class="card"><h2>Spel</h2>
    <div class="row" id="gamestate"></div>
    <div class="row" style="margin-top:10px">
      <button onclick="setState('running')">Start</button>
      <button class="ghost" onclick="setState('paused')">Pauze</button>
      <button class="ghost" onclick="setState('lobby')">Lobby</button>
      <button class="danger" onclick="setState('ended')">Beeindig</button>
    </div>
    <div class="row" style="margin-top:10px">
      <button class="danger" onclick="truce(true)">WAPENSTILSTAND AAN</button>
      <button class="ghost" onclick="truce(false)">wapenstilstand uit</button>
    </div>
    <div class="row" style="margin-top:10px">
      <input id="bc" placeholder="omroepbericht (max 120 tekens)" style="flex:1">
      <button onclick="broadcast()">Verstuur</button>
      <button class="ghost" onclick="broadcast(true)">Wissen</button>
    </div>
  </div>

  <div class="card"><h2>Leiders</h2><div id="leaders"></div></div>
  <div class="card"><h2>Prijzenlijst</h2><div id="hits" class="muted"></div></div>
  <div class="card"><h2>Meer</h2><div class="row">
    <a href="/v1/admin/audit">audit (JSON)</a>
    <a href="/v1/admin/export">export (JSON)</a>
    <a href="/v1/admin/export?fmt=csv">export (CSV)</a>
    <a href="/gotcha/">spelerspagina</a>
  </div></div>
</main>
<script>
async function j(u, opt){ const r = await fetch(u, opt); if(!r.ok) throw new Error(await r.text()); return r.json(); }
// C1: every player-supplied string (display_name, app_version, broadcast) must be
// escaped before it touches innerHTML -- a flashable badge is the stated threat
// model and this dashboard runs same-origin with the gotcha_admin cookie.
function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function stat(n,l,cls){ return '<div class="stat"><div class="n'+(cls?' '+cls:'')+'">'+n+'</div><div class="l">'+l+'</div></div>'; }
async function tick(){
  let d;
  try { d = await j('/v1/admin/dashboard'); }
  catch(e) { document.getElementById('clock').textContent = 'GEEN VERBINDING'; return; }
  const k10 = document.getElementById('k10');
  k10.textContent = d.kills_10m;
  k10.className = 'big' + (d.kills_10m === 0 ? ' warn' : '');
  document.getElementById('k1h').textContent = d.kills_1h;
  document.getElementById('ktot').textContent = d.kills_total;
  document.getElementById('rev10').textContent = d.reveals_10m;
  const p = d.population;
  document.getElementById('pop').innerHTML =
    stat(p.enrolled,'ingeschreven') + stat(p.alive,'in leven') + stat(p.dead,'wacht op respawn') +
    stat(p.protected,'beschermd') + stat(p.opted_out,'uitgeschreven') +
    stat(p.dormant,'slapend', p.dormant>0?'warn':'') + stat(p.stale,'niet gezien');
  const h = d.health;
  document.getElementById('health').innerHTML =
    stat(h.synced_15m,'sync < 15 min') + stat(h.unseen_1h,'niet gezien > 1 u', h.unseen_1h>0?'warn':'') +
    stat(h.rejected_events_1h,'geweigerde events') + stat(h.ring_conflicts,'ring-conflicten', h.ring_conflicts>0?'warn':'') +
    stat(h.flagged_kills,'gemarkeerde kills', h.flagged_kills>0?'warn':'');
  const f = d.fleet;
  document.getElementById('fleet').innerHTML =
    stat(f.below_20,'onder 20%', f.below_20>0?'bad':'') + stat(f.split.app,'app open') +
    stat(f.split.background,'achtergrond');
  document.getElementById('versions').innerHTML = 'versies: ' +
    Object.entries(f.versions).map(([k,v])=>'<span class="pill">'+esc(k)+': '+esc(v)+'</span>').join(' ');
  const g = d.game;
  document.getElementById('gamestate').innerHTML =
    '<span class="pill' + (g.state==='running'?' on':'') + '">' + g.state + '</span>' +
    (g.truce_active ? '<span class="pill warn">WAPENSTILSTAND</span>' : '') +
    (g.broadcast ? '<span class="pill">omroep: ' + esc(g.broadcast) + '</span>' : '');
  const L = d.leaders;
  document.getElementById('leaders').innerHTML =
    '<table><tr><th>#</th><th>speler</th><th>punten</th><th>reeks</th></tr>' +
    L.total.map((e,i)=>'<tr><td>'+(i+1)+'</td><td>'+esc(e.name)+' #'+e.pid+'</td><td>'+e.score+'</td><td>'+e.kills+'</td></tr>').join('') +
    '</table>';
  document.getElementById('hits').innerHTML = L.hitlist.length
    ? L.hitlist.map(x=>'<span class="pill warn">'+esc(x.name)+' #'+x.pid+' &middot; '+x.streak+'</span>').join(' ')
    : 'niemand';
  document.getElementById('clock').textContent = new Date(d.server_time*1000).toLocaleTimeString('nl-BE');
}
async function setState(s){
  if(s==='ended' && !confirm('Spel beeindigen?')) return;
  await j('/v1/admin/game/__GID__/state', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({state:s})}); tick();
}
async function truce(on){
  const body = on ? {active:true, until: Math.floor(Date.now()/1000)+3600, reason:'host'} : {active:false};
  await j('/v1/admin/truce', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body)}); tick();
}
async function broadcast(clear){
  const t = clear ? null : document.getElementById('bc').value;
  await j('/v1/admin/broadcast', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({text:t})}); if(clear) document.getElementById('bc').value=''; tick();
}
function logout(){ const f=document.createElement('form'); f.method='post'; f.action='/admin/logout';
  document.body.appendChild(f); f.submit(); }
tick(); setInterval(tick, 5000);
</script>
"""
    # Deliberately not %-formatted or f-stringed: this blob is HTML, CSS and JS
    # full of literal % signs ("onder 20%") and braces, and both of those
    # mechanisms would either crash on them or need every one escaped.
    body = body.replace("__HOST__", html_escape(host))
    body = body.replace("__GID__", str(int(game["id"])))
    return page("Gotcha dashboard", body)
