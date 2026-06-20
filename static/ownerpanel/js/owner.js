document.addEventListener("DOMContentLoaded", () => {
  const all = document.getElementById("chkAll");
  if (all) {
    all.addEventListener("change", () => {
      document.querySelectorAll(".chkRow").forEach((x) => (x.checked = all.checked));
    });
  }

  const canvas = document.getElementById("demandChart");
  if (canvas && window.SUPPLYAI && window.SUPPLYAI.chartApi) {
    const url = new URL(window.SUPPLYAI.chartApi, window.location.origin);
    if (window.SUPPLYAI.sku) url.searchParams.set("sku", window.SUPPLYAI.sku);

    fetch(url.toString())
      .then((r) => r.json())
      .then((data) => {
        const ctx = canvas.getContext("2d");

        const gradPred = ctx.createLinearGradient(0, 0, 0, 320);
        gradPred.addColorStop(0, "rgba(37,99,235,0.18)");
        gradPred.addColorStop(1, "rgba(37,99,235,0)");

        const gradActual = ctx.createLinearGradient(0, 0, 0, 320);
        gradActual.addColorStop(0, "rgba(22,163,74,0.18)");
        gradActual.addColorStop(1, "rgba(22,163,74,0)");

        new Chart(ctx, {
          type: "line",
          data: {
            labels: data.labels || [],
            datasets: [
              {
                label: "Actual",
                data: data.actual || [],
                tension: 0.35,
                borderWidth: 3,
                pointRadius: 3,
                pointHoverRadius: 5,
                fill: true,
                borderColor: "rgb(22,163,74)",
                backgroundColor: gradActual,
              },
              {
                label: "Forecast",
                data: data.predicted || [],
                tension: 0.35,
                borderWidth: 3,
                pointRadius: 3,
                pointHoverRadius: 5,
                fill: true,
                borderColor: "rgb(37,99,235)",
                backgroundColor: gradPred,
              },
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
              legend: { display: true, labels: { usePointStyle: true, boxWidth: 10 } },
              tooltip: {
                backgroundColor: "rgba(15,23,42,0.92)",
                titleColor: "#fff",
                bodyColor: "#fff",
                padding: 12,
              },
            },
            scales: {
              x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } },
              y: { beginAtZero: true, ticks: { maxTicksLimit: 6 } },
            },
          },
        });
      })
      .catch(() => {});
  }

  const btn = document.getElementById("sidebarToggle");
  const sidebar = document.getElementById("sidebar");
  if (!btn || !sidebar) return;

  const backdrop = document.createElement("div");
  backdrop.className = "sb-backdrop";
  backdrop.style.display = "none";
  document.body.appendChild(backdrop);

  const isMobile = () => window.matchMedia("(max-width: 992px)").matches;

  const closeMobileSidebar = () => {
    document.body.classList.remove("sb-open");
    backdrop.style.display = "none";
    localStorage.setItem("sbMobileOpen", "0");
  };

  const openMobileSidebar = () => {
    document.body.classList.add("sb-open");
    backdrop.style.display = "block";
    localStorage.setItem("sbMobileOpen", "1");
  };

  if (localStorage.getItem("sbHidden") === "1") {
    document.body.classList.add("sb-hidden");
  }

  if (localStorage.getItem("sbMobileOpen") === "1" && isMobile()) {
    openMobileSidebar();
  }

  btn.addEventListener("click", () => {
    if (isMobile()) {
      document.body.classList.contains("sb-open") ? closeMobileSidebar() : openMobileSidebar();
    } else {
      document.body.classList.toggle("sb-hidden");
      localStorage.setItem("sbHidden", document.body.classList.contains("sb-hidden") ? "1" : "0");
    }
  });

  backdrop.addEventListener("click", closeMobileSidebar);
  window.addEventListener("resize", () => {
    if (!isMobile()) closeMobileSidebar();
  });
});