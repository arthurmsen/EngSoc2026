const state = {
  data: [],
  filtered: [],
  map: null,
  markers: null,
  markersById: new Map(),
  selectedOwnerType: "",
  fuse: null
};

const els = {
  search: document.querySelector("#searchInput"),
  uf: document.querySelector("#ufFilter"),
  responsavel: document.querySelector("#responsavelFilter"),
  tag: document.querySelector("#tagFilter"),
  status: document.querySelector("#statusFilter"),
  yearMin: document.querySelector("#yearMin"),
  yearMax: document.querySelector("#yearMax"),
  sortBy: document.querySelector("#sortBy"),
  clear: document.querySelector("#clearFilters"),
  exportCsv: document.querySelector("#exportCsv"),
  cards: document.querySelector("#cards"),
  resultCount: document.querySelector("#resultCount"),
  mapSummary: document.querySelector("#mapSummary"),
  statusChart: document.querySelector("#statusChart"),
  ownerChart: document.querySelector("#ownerChart"),
  detailPanel: document.querySelector("#detailPanel"),
  detailContent: document.querySelector("#detailContent"),
  closeDetail: document.querySelector("#closeDetail"),
  kpiTotal: document.querySelector("#kpiTotal"),
  kpiStates: document.querySelector("#kpiStates")
};

async function init() {
  const response = await fetch("dados.json");
  state.data = await response.json();
  state.filtered = [...state.data];
  state.fuse = new Fuse(state.data, {
    keys: ["titulo", "cidade", "uf", "principal_responsavel", "resumo", "palavras_chave"],
    threshold: 0.25,
    ignoreLocation: true
  });

  buildFilters();
  initMap();
  bindEvents();
  render();
}

function buildFilters() {
  fillSelect(els.uf, "Todas", unique(state.data.map((item) => item.uf)));
  fillSelect(els.responsavel, "Todos", unique(state.data.map((item) => item.principal_responsavel)));
  fillSelect(els.status, "Todos", unique(state.data.map((item) => item.status)));
  fillSelect(els.tag, "Todas", unique(state.data.flatMap((item) => item.palavras_chave)));

  const years = state.data.map((item) => getYear(item.data_inicio));
  els.yearMin.value = Math.min(...years);
  els.yearMax.value = Math.max(...years);
}

function fillSelect(select, allLabel, options) {
  select.innerHTML = [
    `<option value="">${allLabel}</option>`,
    ...options.map((option) => `<option value="${escapeAttr(option)}">${option}</option>`)
  ].join("");
}

function initMap() {
  state.map = L.map("map", { scrollWheelZoom: false }).setView([-14.2, -51.9], 4);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
  }).addTo(state.map);
  state.markers = L.layerGroup().addTo(state.map);
}

function bindEvents() {
  [els.search, els.uf, els.responsavel, els.tag, els.status, els.yearMin, els.yearMax].forEach((el) => {
    el.addEventListener("input", applyFilters);
    el.addEventListener("change", applyFilters);
  });

  els.clear.addEventListener("click", () => {
    els.search.value = "";
    els.uf.value = "";
    els.responsavel.value = "";
    els.tag.value = "";
    els.status.value = "";
    state.selectedOwnerType = "";
    const years = state.data.map((item) => getYear(item.data_inicio));
    els.yearMin.value = Math.min(...years);
    els.yearMax.value = Math.max(...years);
    applyFilters();
  });

  els.exportCsv.addEventListener("click", exportCsv);
  els.sortBy.addEventListener("change", renderCards);
  els.closeDetail.addEventListener("click", () => {
    els.detailPanel.hidden = true;
  });
}

function applyFilters() {
  const query = els.search.value.trim();
  const base = getSearchBase(query);
  const min = Number(els.yearMin.value) || -Infinity;
  const max = Number(els.yearMax.value) || Infinity;

  state.filtered = base.filter((item) => {
    const year = getYear(item.data_inicio);
    return (!els.uf.value || item.uf === els.uf.value)
      && (!els.responsavel.value || item.principal_responsavel === els.responsavel.value)
      && (!els.status.value || item.status === els.status.value)
      && (!state.selectedOwnerType || item.tipo_responsavel === state.selectedOwnerType)
      && (!els.tag.value || item.palavras_chave.includes(els.tag.value))
      && year >= min
      && year <= max;
  });

  render();
}

function getSearchBase(query) {
  if (!query) return state.data;

  const normalizedQuery = normalizeText(query);
  const directMatches = state.data.filter((item) => searchableText(item).includes(normalizedQuery));

  return directMatches.length
    ? directMatches
    : state.fuse.search(query).map((result) => result.item);
}

function render() {
  renderKpis();
  renderMap();
  renderCharts();
  renderCards();
}

function renderKpis() {
  els.kpiTotal.textContent = state.filtered.length;
  els.kpiStates.textContent = unique(state.filtered.map((item) => item.uf)).length;
  els.resultCount.textContent = `${state.filtered.length} resultado${state.filtered.length === 1 ? "" : "s"}`;
}

function renderMap() {
  state.markers.clearLayers();
  state.markersById.clear();
  const bounds = [];
  const locatableItems = state.filtered.filter(hasCoordinates);

  locatableItems.forEach((item) => {
    const coordinates = getCoordinates(item);
    const marker = L.marker(coordinates)
      .bindPopup(`<strong>${item.titulo}</strong><br>${formatLocation(item)}<br>${capitalize(item.status)}`);
    marker.on("click", () => showDetail(item.id));
    marker.addTo(state.markers);
    state.markersById.set(item.id, marker);
    bounds.push(coordinates);
  });

  els.mapSummary.textContent = `${locatableItems.length} ponto${locatableItems.length === 1 ? "" : "s"} com coordenadas no recorte atual.`;

  if (bounds.length) {
    state.map.fitBounds(bounds, { padding: [28, 28], maxZoom: 8 });
  }
}

function renderCharts() {
  renderPieChart(els.statusChart, countBy(state.filtered, "status"), {
    activeValue: els.status.value,
    filterType: "status"
  });
  renderPieChart(els.ownerChart, countBy(state.filtered, "tipo_responsavel"), {
    activeValue: state.selectedOwnerType,
    filterType: "ownerType"
  });
}

function renderPieChart(container, data, options) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((sum, [, value]) => sum + value, 0);

  if (!entries.length || total === 0) {
    container.innerHTML = "<p>Nenhum dado no recorte.</p>";
    return;
  }

  let cursor = 0;
  const segments = entries.map(([label, value], index) => {
    const start = cursor;
    const end = cursor + (value / total) * 100;
    cursor = end;
    return { label, value, color: chartColors[index % chartColors.length], start, end };
  });

  container.innerHTML = `
    <svg class="pie" viewBox="0 0 100 100" role="img" aria-label="Gráfico interativo">
      ${segments.map((segment) => renderPieSegment(segment, options)).join("")}
      <circle class="pie-hole" cx="50" cy="50" r="24"></circle>
      <text class="pie-total" x="50" y="54">${total}</text>
    </svg>
    <div class="pie-legend">
      ${entries.map(([label, value], index) => {
        const percent = Math.round((value / total) * 100);
        return `
          <button
            class="legend-row ${label === options.activeValue ? "selected" : ""}"
            type="button"
            data-filter-type="${options.filterType}"
            data-value="${escapeAttr(label)}"
            title="Filtrar por ${escapeAttr(label)}"
          >
            <span class="legend-color" style="background:${chartColors[index % chartColors.length]}"></span>
            <span class="legend-label" title="${escapeAttr(label)}">${capitalize(label)}</span>
            <span class="legend-value">${percent}% (${value})</span>
          </button>
        `;
      }).join("")}
    </div>
  `;

  container.querySelectorAll("[data-filter-type]").forEach((control) => {
    control.addEventListener("click", () => toggleInsightFilter(control.dataset.filterType, control.dataset.value));
  });
}

function renderPieSegment(segment, options) {
  const selectedClass = segment.label === options.activeValue ? "selected" : "";
  const dataAttrs = `data-filter-type="${options.filterType}" data-value="${escapeAttr(segment.label)}"`;

  if (segment.end - segment.start >= 99.999) {
    return `
      <circle
        class="pie-slice ${selectedClass}"
        ${dataAttrs}
        cx="50"
        cy="50"
        r="46"
        fill="${segment.color}"
      ></circle>
    `;
  }

  return `
    <path
      class="pie-slice ${selectedClass}"
      ${dataAttrs}
      d="${describeArc(50, 50, 46, segment.start, segment.end)}"
      fill="${segment.color}"
    ></path>
  `;
}

function toggleInsightFilter(filterType, value) {
  if (filterType === "status") {
    els.status.value = els.status.value === value ? "" : value;
  }

  if (filterType === "ownerType") {
    state.selectedOwnerType = state.selectedOwnerType === value ? "" : value;
  }

  applyFilters();
}

function renderCards() {
  const sorted = sortItems(state.filtered);

  els.cards.innerHTML = sorted.map((item) => `
    <article class="card">
      <div class="meta">
        <span class="badge ${item.status}">${capitalize(item.status)}</span>
        ${item.uf ? `<span class="tag">${item.uf}</span>` : ""}
        <span class="tag">${getYear(item.data_inicio)}</span>
      </div>
      <h3>${item.titulo}</h3>
      <p>${item.resumo}</p>
      <div class="tags">
        ${item.palavras_chave.slice(0, 4).map((tag) => `<span class="tag">${tag}</span>`).join("")}
      </div>
      <div class="card-actions">
        <button class="ghost-button" type="button" data-id="${item.id}">Ver detalhe</button>
        <a class="link" href="${item.link_acesso}" target="_blank" rel="noreferrer">Fonte</a>
      </div>
    </article>
  `).join("");

  els.cards.querySelectorAll("[data-id]").forEach((button) => {
    button.addEventListener("click", () => showDetail(button.dataset.id));
  });
}

function sortItems(items) {
  const sorted = [...items];
  const sortBy = els.sortBy.value;

  return sorted.sort((a, b) => {
    if (sortBy === "data_asc") return new Date(a.data_inicio) - new Date(b.data_inicio);
    if (sortBy === "nome_asc") return a.titulo.localeCompare(b.titulo, "pt-BR");
    if (sortBy === "nome_desc") return b.titulo.localeCompare(a.titulo, "pt-BR");
    if (sortBy === "status_asc") return a.status.localeCompare(b.status, "pt-BR") || a.titulo.localeCompare(b.titulo, "pt-BR");
    return new Date(b.data_inicio) - new Date(a.data_inicio);
  });
}

function showDetail(id) {
  const item = state.data.find((entry) => entry.id === id);
  if (!item) return;

  els.detailContent.innerHTML = `
    <h2>${item.titulo}</h2>
    <p>${item.resumo}</p>
    <dl>
      <dt>Início</dt><dd>${formatDate(item.data_inicio)}</dd>
      <dt>Fim</dt><dd>${item.data_fim ? formatDate(item.data_fim) : "Em andamento ou não informado"}</dd>
      <dt>Status</dt><dd>${capitalize(item.status)}</dd>
      <dt>Responsável</dt><dd>${item.principal_responsavel}</dd>
      <dt>Tipo</dt><dd>${capitalize(item.tipo_responsavel)}</dd>
      <dt>Local</dt><dd>${formatLocation(item)}</dd>
      <dt>Abrangência</dt><dd>${capitalize(item.abrangencia)}</dd>
      <dt>Palavras-chave</dt><dd>${item.palavras_chave.join(", ")}</dd>
      <dt>Fonte</dt><dd>${item.fonte}</dd>
      <dt>Atualizado em</dt><dd>${formatDate(item.ultima_atualizacao)}</dd>
    </dl>
    <p><a class="link" href="${item.link_acesso}" target="_blank" rel="noreferrer">Acessar referência</a></p>
  `;
  els.detailPanel.hidden = false;
  focusMapOnItem(item);
}

function focusMapOnItem(item) {
  const marker = state.markersById.get(item.id);
  if (!hasCoordinates(item)) return;

  state.map.flyTo(getCoordinates(item), 11, { duration: 0.9 });

  if (marker) {
    marker.openPopup();
  }
}

function exportCsv() {
  const headers = [
    "id", "titulo", "data_inicio", "data_fim", "status", "principal_responsavel",
    "tipo_responsavel", "resumo", "link_acesso", "uf", "cidade", "abrangencia",
    "palavras_chave", "fonte", "ultima_atualizacao", "latitude", "longitude"
  ];
  const rows = state.filtered.map((item) => headers.map((header) => {
    const value = Array.isArray(item[header]) ? item[header].join("; ") : item[header] ?? "";
    return `"${String(value).replaceAll('"', '""')}"`;
  }).join(","));
  const csv = [headers.join(","), ...rows].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "moedas-sociais-filtrado.csv";
  anchor.click();
  URL.revokeObjectURL(url);
}

function countBy(items, key) {
  return items.reduce((acc, item) => {
    acc[item[key]] = (acc[item[key]] || 0) + 1;
    return acc;
  }, {});
}

const chartColors = ["#0c6b58", "#315f9d", "#b46a00", "#8a4f9f", "#ba3d48", "#58713f", "#286f83"];

function describeArc(cx, cy, radius, startPercent, endPercent) {
  const start = polarToCartesian(cx, cy, radius, endPercent);
  const end = polarToCartesian(cx, cy, radius, startPercent);
  const largeArcFlag = endPercent - startPercent <= 50 ? "0" : "1";

  return [
    `M ${cx} ${cy}`,
    `L ${start.x} ${start.y}`,
    `A ${radius} ${radius} 0 ${largeArcFlag} 0 ${end.x} ${end.y}`,
    "Z"
  ].join(" ");
}

function polarToCartesian(cx, cy, radius, percent) {
  const angle = ((percent / 100) * 360 - 90) * Math.PI / 180;

  return {
    x: cx + radius * Math.cos(angle),
    y: cy + radius * Math.sin(angle)
  };
}

function searchableText(item) {
  return normalizeText([
    item.titulo,
    item.cidade,
    item.uf,
    item.principal_responsavel,
    item.tipo_responsavel,
    item.resumo,
    item.status,
    item.abrangencia,
    item.palavras_chave.join(" ")
  ].join(" "));
}

function hasCoordinates(item) {
  if (item.latitude === null || item.latitude === undefined || item.latitude === "") return false;
  if (item.longitude === null || item.longitude === undefined || item.longitude === "") return false;

  return Number.isFinite(Number(item.latitude)) && Number.isFinite(Number(item.longitude));
}

function getCoordinates(item) {
  return [Number(item.latitude), Number(item.longitude)];
}

function formatLocation(item) {
  if (item.cidade && item.uf) return `${item.cidade}/${item.uf}`;
  if (item.cidade) return item.cidade;
  if (item.uf) return item.uf;
  return "Localidade não informada";
}

function normalizeText(value) {
  return String(value)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function unique(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => String(a).localeCompare(String(b), "pt-BR"));
}

function getYear(date) {
  // Se dateString for null, undefined ou vazio, retorna um valor padrão (ex: 'Sem ano' ou 0)
  if (!dateString) return "Sem ano"; 
  
  // Se não for nulo, faz o slice normalmente
  return dateString.slice(0, 4);
  
  const parsedDate = parseDateValue(date);
  return parsedDate ? parsedDate.getUTCFullYear() : NaN;
}

function formatDate(date) {
  const parsedDate = parseDateValue(date);
  if (!parsedDate) return "Não informado";

  return new Intl.DateTimeFormat("pt-BR", { timeZone: "UTC" }).format(parsedDate);
}

function parseDateValue(value) {
  if (value === null || value === undefined || value === "") return null;

  if (typeof value === "number" || /^\d+(\.\d+)?$/.test(String(value))) {
    const serial = Number(value);
    if (Number.isFinite(serial) && serial > 20000) {
      const excelEpoch = Date.UTC(1899, 11, 30);
      return new Date(excelEpoch + serial * 24 * 60 * 60 * 1000);
    }
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function capitalize(value) {
  return String(value).replaceAll("_", " ").replace(/^\w/, (letter) => letter.toUpperCase());
}

function escapeAttr(value) {
  return String(value).replaceAll('"', "&quot;");
}

init().catch((error) => {
  document.body.innerHTML = `<main><h1>Erro ao carregar dados</h1><p>${error.message}</p></main>`;
});
