/**
 * static/js/autocomplete.js
 * Widget de autocomplete reutilizable (rúbrica C4 — JS en frontend).
 * Uso:
 *   initAutocomplete(inputEl, endpointUrl, { onSelect })
 *
 * Nota IA (Claude): implementación propia sin librerías externas,
 * usando fetch() + teclado accesible (ArrowUp/Down/Enter/Escape).
 */

function initAutocomplete(inputEl, endpointUrl, opciones = {}) {
  const { onSelect = null, minChars = 1, delay = 200 } = opciones;

  // Contenedor del desplegable
  const dropdown = document.createElement("ul");
  dropdown.className = "ac-dropdown list-unstyled mb-0";
  dropdown.setAttribute("role", "listbox");
  inputEl.parentNode.style.position = "relative";
  inputEl.parentNode.appendChild(dropdown);

  let timer       = null;
  let activeIndex = -1;
  let ultimaQuery = "";

  function cerrar() {
    dropdown.innerHTML = "";
    dropdown.classList.remove("ac-open");
    activeIndex = -1;
  }

  function marcarActivo(index) {
    const items = dropdown.querySelectorAll("li");
    items.forEach((li, i) => li.classList.toggle("ac-active", i === index));
    activeIndex = index;
  }

  function seleccionar(valor) {
    inputEl.value = valor;
    cerrar();
    if (onSelect) onSelect(valor);
    // Disparar evento de cambio para que otros listeners reaccionen
    inputEl.dispatchEvent(new Event("change", { bubbles: true }));
  }

  async function buscar(q) {
    if (q === ultimaQuery) return;
    ultimaQuery = q;

    if (q.length < minChars) { cerrar(); return; }

    try {
      const url = `${endpointUrl}?q=${encodeURIComponent(q)}`;
      const res  = await fetch(url, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      if (!res.ok) { cerrar(); return; }

      const data = await res.json();
      const sug  = data.sugerencias || [];

      dropdown.innerHTML = "";
      if (!sug.length) { cerrar(); return; }

      sug.forEach((s, i) => {
        const li = document.createElement("li");
        li.setAttribute("role", "option");
        li.setAttribute("data-value", s);
        // Resaltar la parte que coincide con la query
        const idx = s.toLowerCase().indexOf(q.toLowerCase());
        if (idx >= 0) {
          li.innerHTML =
            escapeHtml(s.slice(0, idx)) +
            `<strong>${escapeHtml(s.slice(idx, idx + q.length))}</strong>` +
            escapeHtml(s.slice(idx + q.length));
        } else {
          li.textContent = s;
        }
        li.addEventListener("mousedown", (e) => {
          e.preventDefault(); // evitar que el input pierda el foco antes de seleccionar
          seleccionar(s);
        });
        li.addEventListener("mouseenter", () => marcarActivo(i));
        dropdown.appendChild(li);
      });

      dropdown.classList.add("ac-open");
      activeIndex = -1;

    } catch (_) {
      cerrar();
    }
  }

  // ── Eventos del input ────────────────────────────────────────
  inputEl.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => buscar(inputEl.value.trim()), delay);
  });

  inputEl.addEventListener("keydown", (e) => {
    const items = dropdown.querySelectorAll("li");
    if (!dropdown.classList.contains("ac-open")) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      marcarActivo(Math.min(activeIndex + 1, items.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      marcarActivo(Math.max(activeIndex - 1, 0));
    } else if (e.key === "Enter" && activeIndex >= 0) {
      e.preventDefault();
      seleccionar(items[activeIndex].dataset.value);
    } else if (e.key === "Escape") {
      cerrar();
    }
  });

  inputEl.addEventListener("focus", () => {
    if (inputEl.value.trim().length >= minChars) {
      buscar(inputEl.value.trim());
    }
  });

  // Cerrar al hacer clic fuera
  document.addEventListener("click", (e) => {
    if (!inputEl.parentNode.contains(e.target)) cerrar();
  });

  function escapeHtml(str) {
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
}
