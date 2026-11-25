// NerdCore frontend. Vanilla JS, no build step.
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// Anonymous per-browser id so your conversation list is yours. Falls back to memory if storage is blocked.
let READER = null;
try { READER = localStorage.getItem("nerdcore_reader"); if (!READER) { READER = crypto.randomUUID(); localStorage.setItem("nerdcore_reader", READER); } }
catch { READER = crypto.randomUUID(); }

const S = { books: [], bySlug: {}, mode: "library", book: null, conv: null, busy: false, reader: null };
const STARTERS = [
  "How do I stay calm when things go wrong?",
  "What makes a good friend?",
  "Is it better to be feared or loved as a leader?",
  "Why does the division of labour make nations rich?",
  "What is happiness?",
];

async function api(path, opts = {}) {
  const r = await fetch(`/api${path}`, { ...opts, headers: { "Content-Type": "application/json", "X-Reader-Id": READER, ...(opts.headers || {}) } });
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail; } catch {} throw new Error(m); }
  return r.status === 204 ? null : r.json();
}

function mark(text, terms) {
  let out = esc(text);
  if (!terms?.length) return out;
  // highlight whole words that start with a query stem, e.g. "anger" matches "angry", "angered"
  const rx = new RegExp(`\\b(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})\\w*`, "gi");
  return out.replace(rx, "<mark>$&</mark>");
}

// ------------------------------------------------------------------ shelf + modes
function renderShelf() {
  $("#shelf").innerHTML = S.books.map((b, i) => `
    <button class="book ${S.book === b.slug && S.mode === "book" ? "on" : ""}" role="listitem" data-slug="${b.slug}"
      style="--c:${b.color}; height:${150 + ((b.pages % 5) * 7)}px; animation-delay:${i * 70}ms" title="${esc(b.title)} · ${esc(b.author)} · ${b.year}">
      ${esc(b.title.replace(/^The /, ""))}<small>${esc(b.author)}</small>
    </button>`).join("");
  $("#starters").innerHTML = STARTERS.map((s) => `<button class="chip">${esc(s)}</button>`).join("");
}

function setMode(mode, book = S.book) {
  S.mode = mode;
  S.book = mode === "book" ? book || S.books[0].slug : S.book;
  document.querySelectorAll(".modes button").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
  const bk = S.bySlug[S.book];
  $("#book-label").textContent = mode === "book" && bk ? `· ${bk.title}` : "";
  $("#mode-hint").textContent = mode === "library" ? "Searching all seven books."
    : mode === "thinkers" ? "One passage from each author, side by side. Good for big questions."
    : `Only ${bk.title} by ${bk.author}. Click a book on the shelf to switch.`;
  renderShelf();
}

$("#shelf").addEventListener("click", (e) => {
  const b = e.target.closest(".book"); if (!b) return;
  if (S.mode === "book" && S.book === b.dataset.slug) setMode("library");
  else setMode("book", b.dataset.slug);
  $("#q").focus();
});
$("#starters").addEventListener("click", (e) => { const c = e.target.closest(".chip"); if (c) ask(c.textContent); });
document.querySelectorAll(".modes button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));

// ------------------------------------------------------------------ thread
function showThread() { $("#welcome").hidden = true; $("#thread").hidden = false; }

function sourceCard(s, terms) {
  const b = S.bySlug[s.book] || {};
  return `<article class="src" style="--c:${b.color}">
    <header><span class="n">[${s.n}]</span><b>${esc(s.author)}</b><span>${esc(s.title)} · p. ${s.page}</span>
      <span class="rel" title="Relevance"><i style="width:${Math.round(s.relevance * 100)}%"></i></span></header>
    <blockquote>${mark(s.text, terms)}</blockquote>
    <footer><button data-more>Expand</button><button data-read="${s.book}:${s.page}">Read the full page →</button></footer>
  </article>`;
}

function botHTML(r) {
  const text = esc(r.answer).replace(/\[(\d+)\]/g, '<sup data-n="$1">[$1]</sup>');
  const note = r.mode === "passages" ? `<p class="note">Showing the passages directly. Add a GROQ_API_KEY for a written explanation.</p>` : "";
  return `<p class="a-text">${text}</p>
    <div class="sources ${r.sources.length > 2 && S.mode === "thinkers" ? "thinkers" : ""}">${r.sources.map((s) => sourceCard(s, r.terms)).join("")}</div>${note}`;
}

function add(cls, html) {
  const d = document.createElement("div");
  d.className = cls; d.innerHTML = html;
  $("#thread").append(d);
  d.scrollIntoView({ behavior: "smooth", block: "start" });
  return d;
}

async function ask(question) {
  question = question.trim();
  if (!question || S.busy) return;
  S.busy = true; $(".send").disabled = true;
  showThread();
  add("q-user", esc(question));
  const slot = add("a-bot", `<p class="thinking">Searching the shelves</p>`);
  try {
    const r = await api("/ask", { method: "POST", body: JSON.stringify({ question, mode: S.mode, book: S.mode === "book" ? S.book : null, conversation_id: S.conv }) });
    const fresh = !S.conv;
    S.conv = r.conversation_id;
    slot.innerHTML = botHTML(r);
    if (fresh) loadHistory();
  } catch (e) { slot.innerHTML = `<p class="a-text">${esc(e.message)}</p>`; }
  finally { S.busy = false; $(".send").disabled = false; }
}

$("#thread").addEventListener("click", (e) => {
  const more = e.target.closest("[data-more]");
  if (more) { const card = more.closest(".src"); card.classList.toggle("open"); more.textContent = card.classList.contains("open") ? "Collapse" : "Expand"; return; }
  const read = e.target.closest("[data-read]");
  if (read) { const [book, page] = read.dataset.read.split(":"); const terms = [...read.closest(".src").querySelectorAll("mark")].map((m) => m.textContent.toLowerCase()); openReader(book, +page, terms); return; }
  const sup = e.target.closest("sup[data-n]");
  if (sup) { const cards = sup.closest(".a-bot").querySelectorAll(".src"); const c = [...cards].find((x) => x.querySelector(".n").textContent === `[${sup.dataset.n}]`); c?.scrollIntoView({ behavior: "smooth", block: "center" }); c?.animate([{ boxShadow: "0 0 0 2px #d9a85b" }, { boxShadow: "none" }], { duration: 1400 }); }
});

// ------------------------------------------------------------------ composer
const q = $("#q");
q.addEventListener("input", () => { q.style.height = "auto"; q.style.height = `${Math.min(q.scrollHeight, 180)}px`; });
q.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#ask").requestSubmit(); } });
$("#ask").addEventListener("submit", (e) => { e.preventDefault(); const v = q.value; q.value = ""; q.style.height = "auto"; ask(v); });

// ------------------------------------------------------------------ reader
async function openReader(book, page, terms = []) {
  S.reader = { book, page, terms };
  const d = await api(`/books/${book}/pages/${page}`);
  $("#r-title").textContent = d.title;
  $("#r-meta").textContent = `${d.author} · page ${d.page}`;
  $("#r-text").innerHTML = mark(d.text, terms);
  $("#r-prev").disabled = !d.prev; $("#r-next").disabled = !d.next;
  if (!$("#reader").open) $("#reader").showModal();
  $("#r-text").scrollTop = 0;
}
$("#r-close").onclick = () => $("#reader").close();
$("#r-prev").onclick = () => openReader(S.reader.book, S.reader.page - 1, S.reader.terms);
$("#r-next").onclick = () => openReader(S.reader.book, S.reader.page + 1, S.reader.terms);
$("#reader").addEventListener("click", (e) => { if (e.target.id === "reader") $("#reader").close(); });

// ------------------------------------------------------------------ history
async function loadHistory() {
  const term = $("#hist-search").value.trim();
  const list = await api(`/conversations${term ? `?q=${encodeURIComponent(term)}` : ""}`);
  $("#history").innerHTML = list.length ? list.map((c) => `
    <div class="h-item ${c.id === S.conv ? "on" : ""}" data-id="${c.id}" role="button" tabindex="0">
      <span>${esc(c.title)}</span><button class="act" data-rename title="Rename">✎</button><button class="act" data-del title="Delete">✕</button>
    </div>`).join("") : `<p class="h-empty">${term ? "No matches." : "Your conversations will appear here."}</p>`;
}
let searchT;
$("#hist-search").addEventListener("input", () => { clearTimeout(searchT); searchT = setTimeout(loadHistory, 250); });

$("#history").addEventListener("click", async (e) => {
  const item = e.target.closest(".h-item"); if (!item) return;
  const id = item.dataset.id;
  if (e.target.closest("[data-del]")) {
    if (!confirm("Delete this conversation?")) return;
    await api(`/conversations/${id}`, { method: "DELETE" });
    if (S.conv === id) newChat();
    return loadHistory();
  }
  if (e.target.closest("[data-rename]")) {
    const t = prompt("Rename conversation", item.querySelector("span").textContent);
    if (t?.trim()) { await api(`/conversations/${id}`, { method: "PATCH", body: JSON.stringify({ title: t.trim() }) }); loadHistory(); }
    return;
  }
  const c = await api(`/conversations/${id}`);
  S.conv = id;
  setMode(c.mode, c.book);
  $("#thread").innerHTML = "";
  showThread();
  for (let i = 0; i < c.messages.length; i++) {
    const m = c.messages[i];
    if (m.role === "user") add("q-user", esc(m.content));
    else add("a-bot", botHTML({ answer: m.content, sources: m.sources || [], terms: [], mode: "llm" }));
  }
  $("#sidebar").classList.remove("open");
  loadHistory();
});

function newChat() {
  S.conv = null;
  $("#thread").innerHTML = ""; $("#thread").hidden = true; $("#welcome").hidden = false;
  loadHistory(); q.focus();
}
$("#new-chat").onclick = newChat;
$("#menu").onclick = () => $("#sidebar").classList.toggle("open");

// ------------------------------------------------------------------ boot
(async () => {
  try {
    const [books, h] = await Promise.all([api("/books"), api("/health")]);
    S.books = books; S.bySlug = Object.fromEntries(books.map((b) => [b.slug, b]));
    $("#stats").textContent = `${h.books} books · ${h.pages.toLocaleString()} pages · ${h.passages.toLocaleString()} passages indexed · ${h.llm ? "AI explanations on" : "passages mode"}`;
    setMode("library");
    loadHistory();
  } catch (e) { $("#welcome .lede").textContent = `Can't reach the server: ${e.message}`; }
})();
