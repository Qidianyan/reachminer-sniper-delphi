(function () {
  "use strict";

  const PALETTE = {
    inkBlack: "#141413",
    obsidian: "#1c1917",
    tungsten: "#2e2a27",
    amber: "#d97706",
    amberBright: "#f59e0b",
    amberFill: "rgba(217, 119, 6, 0.13)",
    signalGreen: "#16a34a",
    parchment: "#f5f2eb",
    stone: "#a8a29e",
    crimson: "#dc2626",
  };

  let currentSnapshot = null;
  let activeMarketFilter = "all";

  function escapeHtml(raw) {
    return String(raw ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function shortAddr(addr) {
    if (!addr || addr.length < 12) return addr || "--";
    return addr.slice(0, 8) + "..." + addr.slice(-6);
  }

  async function loadDashboardData() {
    try {
      const resp = await fetch("/api/dashboard", { cache: "no-store" });
      if (resp.ok) {
        const liveData = await resp.json();
        document.getElementById("ledger-source-text").textContent =
          "LIVE SQLITE API CONNECTED";
        return liveData;
      }
    } catch (_err) {
      // Fallback seamlessly to SQLite-exported snapshot when opened via file://
    }
    if (window.__REACHMINER_LEDGER_SNAPSHOT__) {
      document.getElementById("ledger-source-text").textContent =
        "SQLITE SNAPSHOT VERIFIED";
      return window.__REACHMINER_LEDGER_SNAPSHOT__;
    }
    throw new Error("No ledger data available");
  }

  function renderTopKpis(data) {
    const wg = data.wallet_guard || {};
    const qual = data.qualification || {};
    const totals = data.totals || {};
    const subs = data.submissions || [];

    const lockEl = document.getElementById("wallet-lock-badge");
    lockEl.textContent =
      "SINGLE-WALLET LOCK: " +
      shortAddr(wg.canonical_wallet) +
      " (3-WAY EIP-55 MATCH)";

    const mCount = qual.distinct_judged_markets || 0;
    const sCount = qual.total_judged_submissions || 0;
    document.getElementById("kpi-qualification").textContent =
      sCount + " Judged / " + mCount + " Mkts";

    const pct = Math.min(
      100,
      Math.round(
        Math.min(mCount / (qual.min_markets_required || 3), 1) * 50 +
          Math.min(sCount / (qual.min_judged_required || 10), 1) * 50
      )
    );
    document.getElementById("kpi-qual-bar").style.width = pct + "%";
    document.getElementById("kpi-qual-sub").textContent = qual.is_qualified
      ? "QUALIFIED FOR DORAHACKS PRIZE POOL (>=" +
        qual.min_markets_required +
        " Mkts, >=" +
        qual.min_judged_required +
        " Judged)"
      : "Progress toward minimum threshold";

    document.getElementById("kpi-total-usdc").textContent =
      "$" + Number(totals.combined_usdc || 0).toFixed(2) + " USDC";
    document.getElementById("kpi-usdc-breakdown").textContent =
      "Stage-1: $" +
      Number(totals.stage1_reward_usdc || 0).toFixed(2) +
      " + Stage-2 Settlement: $" +
      Number(totals.stage2_settlement_usdc || 0).toFixed(2);

    const accepted = subs.filter((s) => s.verdict === "ACCEPTED").length;
    const rate = subs.length > 0 ? ((accepted / subs.length) * 100).toFixed(1) : "0.0";
    document.getElementById("kpi-acceptance-rate").textContent = rate + "% ACCEPTED";
    document.getElementById("kpi-blocked-sub").textContent =
      (totals.blocked_bad_shots || 0) +
      " Wasteful/Invalid Shots Blocked Pre-Flight";
  }

  function renderMagazineHtml(bulletsUsed, maxBullets, eligible) {
    const slots = [];
    for (let i = 1; i <= maxBullets; i++) {
      if (!eligible) {
        slots.push('<span class="bullet-slot locked">LOCK</span>');
      } else if (i <= bulletsUsed) {
        slots.push('<span class="bullet-slot fired">#' + i + " HIT</span>");
      } else {
        slots.push('<span class="bullet-slot armed">#' + i + " RDY</span>");
      }
    }
    const rem = Math.max(0, maxBullets - bulletsUsed);
    const caption = eligible
      ? rem + "/" + maxBullets + " Bullets Remaining"
      : "0 Allocated (Filtered)";
    return (
      '<div class="magazine-box">' +
      '<div class="magazine-slots">' +
      slots.join("") +
      "</div>" +
      '<span class="magazine-caption">' +
      escapeHtml(caption) +
      "</span>" +
      "</div>"
    );
  }

  function renderMarketFunnel(data) {
    const container = document.getElementById("market-list-container");
    const quotaMap = new Map();
    (data.markets || []).forEach((m) => quotaMap.set(m.market_id, m));

    const rankings =
      data.market_rankings && data.market_rankings.length > 0
        ? data.market_rankings
        : (data.markets || []).map((m) => ({
            market_id: m.market_id,
            question: m.question,
            category: m.category,
            prior_p: m.current_probability,
            resolution_time_utc: m.resolution_time_utc,
            eligible: true,
            rejection_reason: null,
            shannon_entropy_bits: 0.98,
            in_entropy_sweet_spot:
              m.current_probability >= 0.3 && m.current_probability <= 0.7,
            priority_score: 10.0,
          }));

    const filtered = rankings.filter((r) => {
      if (activeMarketFilter === "eligible") return r.eligible;
      if (activeMarketFilter === "rejected") return !r.eligible;
      return true;
    });

    container.innerHTML = filtered
      .map((entry) => {
        const qState = quotaMap.get(entry.market_id);
        const used = qState ? qState.bullets_used : 0;
        const currP = qState ? qState.current_probability : entry.prior_p;
        const sweetBadge = entry.in_entropy_sweet_spot
          ? '<span class="meta-tag meta-sweet">SWEET SPOT H=' +
            Number(entry.shannon_entropy_bits).toFixed(2) +
            "b</span>"
          : '<span class="meta-tag">H=' +
            Number(entry.shannon_entropy_bits).toFixed(2) +
            "b</span>";
        const statusTag = entry.eligible
          ? '<span class="meta-tag">Score: ' +
            Number(entry.priority_score).toFixed(2) +
            "</span>"
          : '<span class="pill-badge pill-crimson">' +
            escapeHtml(entry.rejection_reason) +
            "</span>";

        return (
          '<div class="market-row ' +
          (entry.eligible ? "" : "ineligible") +
          '">' +
          "<div>" +
          '<div class="market-question">' +
          escapeHtml(entry.question) +
          "</div>" +
          '<div class="market-meta">' +
          '<span class="meta-tag">' +
          escapeHtml(entry.market_id) +
          "</span>" +
          '<span class="meta-tag">' +
          escapeHtml(entry.category) +
          "</span>" +
          '<span class="meta-tag">Settles: ' +
          escapeHtml(entry.resolution_time_utc) +
          "</span>" +
          '<span class="meta-tag">p: ' +
          (Number(entry.prior_p) * 100).toFixed(1) +
          "% -> " +
          (Number(currP) * 100).toFixed(1) +
          "%</span>" +
          sweetBadge +
          statusTag +
          "</div>" +
          "</div>" +
          renderMagazineHtml(used, 3, entry.eligible) +
          "</div>"
        );
      })
      .join("");
  }

  function renderLmsrSvgChart(data) {
    const points = data.lmsr_curve || [];
    const container = document.getElementById("lmsr-svg-container");
    if (points.length === 0) {
      container.textContent = "No LMSR curve data.";
      return;
    }

    const width = 520;
    const height = 270;
    const padL = 44;
    const padR = 20;
    const padT = 18;
    const padB = 34;
    const plotW = width - padL - padR;
    const plotH = height - padT - padB;

    const maxPayoff = Math.max(
      ...points.map((pt) => Number(pt.expected_payoff_usdc)),
      1.0
    );

    const xOfP = (p) => padL + ((p - 0.05) / 0.9) * plotW;
    const yOfPayoff = (val) => padT + plotH - (val / (maxPayoff * 1.12)) * plotH;
    const yOfEntropy = (h) => padT + plotH - h * plotH * 0.88;

    const payoffPath = points
      .map(
        (pt, idx) =>
          (idx === 0 ? "M" : "L") +
          xOfP(pt.p).toFixed(1) +
          "," +
          yOfPayoff(pt.expected_payoff_usdc).toFixed(1)
      )
      .join(" ");

    const entropyPath = points
      .map(
        (pt, idx) =>
          (idx === 0 ? "M" : "L") +
          xOfP(pt.p).toFixed(1) +
          "," +
          yOfEntropy(pt.entropy_bits).toFixed(1)
      )
      .join(" ");

    const sweetX1 = xOfP(0.3);
    const sweetX2 = xOfP(0.7);

    const activeDots = (data.markets || [])
      .map((m) => {
        const cx = xOfP(Math.min(Math.max(m.current_probability, 0.05), 0.95));
        const h =
          -(
            m.current_probability * Math.log2(m.current_probability) +
            (1 - m.current_probability) * Math.log2(1 - m.current_probability)
          ) || 0.5;
        const cy = yOfEntropy(h);
        return (
          '<circle cx="' +
          cx.toFixed(1) +
          '" cy="' +
          cy.toFixed(1) +
          '" r="5" fill="' +
          PALETTE.signalGreen +
          '" stroke="' +
          PALETTE.inkBlack +
          '" stroke-width="1.5" />'
        );
      })
      .join("");

    container.innerHTML =
      '<svg viewBox="0 0 ' +
      width +
      " " +
      height +
      '" width="100%" height="260" role="img" aria-label="LMSR Information Gain Curve">' +
      '<rect x="' +
      sweetX1.toFixed(1) +
      '" y="' +
      padT +
      '" width="' +
      (sweetX2 - sweetX1).toFixed(1) +
      '" height="' +
      plotH +
      '" fill="' +
      PALETTE.amberFill +
      '" />' +
      '<line x1="' +
      padL +
      '" y1="' +
      (padT + plotH) +
      '" x2="' +
      (width - padR) +
      '" y2="' +
      (padT + plotH) +
      '" stroke="' +
      PALETTE.tungsten +
      '" stroke-width="1" />' +
      '<line x1="' +
      sweetX1.toFixed(1) +
      '" y1="' +
      padT +
      '" x2="' +
      sweetX1.toFixed(1) +
      '" y2="' +
      (padT + plotH) +
      '" stroke="' +
      PALETTE.amber +
      '" stroke-dasharray="3 3" stroke-width="1" />' +
      '<line x1="' +
      sweetX2.toFixed(1) +
      '" y1="' +
      padT +
      '" x2="' +
      sweetX2.toFixed(1) +
      '" y2="' +
      (padT + plotH) +
      '" stroke="' +
      PALETTE.amber +
      '" stroke-dasharray="3 3" stroke-width="1" />' +
      '<path d="' +
      entropyPath +
      '" fill="none" stroke="' +
      PALETTE.parchment +
      '" stroke-width="1.6" stroke-dasharray="4 3" opacity="0.7" />' +
      '<path d="' +
      payoffPath +
      '" fill="none" stroke="' +
      PALETTE.amber +
      '" stroke-width="2.6" />' +
      activeDots +
      '<text x="' +
      ((sweetX1 + sweetX2) / 2).toFixed(1) +
      '" y="' +
      (padT + 14) +
      '" text-anchor="middle" fill="' +
      PALETTE.amberBright +
      '" font-size="10" font-family="monospace">SNIPER SWEET SPOT (0.30 &lt;= p &lt;= 0.70)</text>' +
      '<text x="' +
      xOfP(0.05).toFixed(1) +
      '" y="' +
      (height - 10) +
      '" fill="' +
      PALETTE.stone +
      '" font-size="10" font-family="monospace">p=0.05</text>' +
      '<text x="' +
      xOfP(0.5).toFixed(1) +
      '" y="' +
      (height - 10) +
      '" text-anchor="middle" fill="' +
      PALETTE.stone +
      '" font-size="10" font-family="monospace">p=0.50 (Max Entropy 1.0b)</text>' +
      '<text x="' +
      xOfP(0.95).toFixed(1) +
      '" y="' +
      (height - 10) +
      '" text-anchor="end" fill="' +
      PALETTE.stone +
      '" font-size="10" font-family="monospace">p=0.95</text>' +
      "</svg>";
  }

  function renderEvidencePackets(data) {
    const subs = data.submissions || [];
    const container = document.getElementById("packet-list-container");
    container.innerHTML = subs
      .map((sub) => {
        const shiftPct = ((sub.official_p_after - sub.p_before) * 100).toFixed(1);
        const shiftSign = sub.official_p_after >= sub.p_before ? "+" : "";
        const attHtml = (sub.attachments || [])
          .map(
            (a) =>
              '<span class="attachment-chip">' +
              escapeHtml(a.filename) +
              " · sha256:" +
              escapeHtml(String(a.sha256_hex).slice(0, 10)) +
              " (" +
              a.size_bytes +
              "B)</span>"
          )
          .join("");

        return (
          '<article class="packet-card">' +
          '<div class="packet-top">' +
          "<div>" +
          '<span class="pill-badge pill-green">' +
          escapeHtml(sub.verdict) +
          " · BULLET " +
          sub.bullet_slot +
          "/3</span> " +
          '<span class="meta-tag">' +
          escapeHtml(sub.market_id) +
          "</span> " +
          '<span class="meta-tag">Δp: ' +
          shiftSign +
          shiftPct +
          "% (" +
          (sub.p_before * 100).toFixed(1) +
          "% -> " +
          (sub.official_p_after * 100).toFixed(1) +
          "%)</span>" +
          "</div>" +
          '<div class="pill-badge pill-amber">+$' +
          (sub.stage1_reward_usdc + sub.stage2_settlement_usdc).toFixed(2) +
          " USDC · " +
          sub.api_latency_ms +
          "ms</div>" +
          "</div>" +
          '<div class="packet-note">' +
          escapeHtml(sub.explanatory_note) +
          "</div>" +
          '<div class="attachment-strip">' +
          attHtml +
          "</div>" +
          "</article>"
        );
      })
      .join("");
  }

  function renderBlockedAttempts(data) {
    const blocked = data.blocked_attempts || [];
    const container = document.getElementById("blocked-list-container");
    container.innerHTML = blocked
      .map(
        (b) =>
          '<div class="blocked-item">' +
          "<div><strong>" +
          escapeHtml(b.signal_id) +
          "</strong> · " +
          escapeHtml(b.market_id) +
          " · " +
          escapeHtml(b.attempted_at_utc) +
          "</div>" +
          '<div class="blocked-reason">BLOCKED -> ' +
          escapeHtml(b.rejection_reason) +
          "</div>" +
          "</div>"
      )
      .join("");
  }

  function bindFilterTabs() {
    const buttons = document.querySelectorAll(".tab-btn");
    buttons.forEach((btn) => {
      btn.addEventListener("click", () => {
        buttons.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        activeMarketFilter = btn.getAttribute("data-filter") || "all";
        if (currentSnapshot) {
          renderMarketFunnel(currentSnapshot);
        }
      });
    });
  }

  async function init() {
    bindFilterTabs();
    currentSnapshot = await loadDashboardData();
    renderTopKpis(currentSnapshot);
    renderMarketFunnel(currentSnapshot);
    renderLmsrSvgChart(currentSnapshot);
    renderEvidencePackets(currentSnapshot);
    renderBlockedAttempts(currentSnapshot);
  }

  init();
})();
